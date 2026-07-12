# backend/projects/service.py
# Project Management Service Layer

from datetime import datetime
from typing import Optional, List, Dict, Any
from bson import ObjectId
import uuid

from .models import (
    Project, ProjectCreate, ProjectUpdate, ProjectStatus, ProjectPriority,
    Task, TaskCreate, TaskUpdate, TaskStatus, TaskPriority,
    TeamMember, Milestone, MilestoneStatus, TimeEntry, ProjectStats
)


class ProjectService:
    """Service class for project management operations"""
    
    def __init__(self, db):
        self.db = db
        # db is a DatabaseManager, get the torpedo_settings database
        settings_db = db.get_database("torpedo_settings")
        self.projects = settings_db["projects"]
        self.tasks = settings_db["tasks"]
        self.time_entries = settings_db["time_entries"]
    
    # ==================== PROJECTS ====================
    
    def create_project(self, data: ProjectCreate, created_by: str = None) -> Dict[str, Any]:
        """Create a new project"""
        # Generate project code if not provided
        project_code = data.code
        if not project_code:
            count = self.projects.count_documents({})
            project_code = f"PRJ-{count + 1:04d}"
        
        project_doc = {
            **data.model_dump(exclude={"code"}),
            "code": project_code,
            "status": ProjectStatus.PLANNING.value,
            "progress_percent": 0,
            "total_tasks": 0,
            "completed_tasks": 0,
            "budget_spent": 0,
            "team_members": [],
            "milestones": [],
            "created_at": datetime.utcnow(),
            "created_by": created_by,
            "is_archived": False
        }
        
        result = self.projects.insert_one(project_doc)
        project_doc["_id"] = result.inserted_id

        # Mirror into the canonical CRM spine (best-effort, non-fatal)
        try:
            try:
                from app.services.spine_connector import mirror_ops_project_to_spine
            except ImportError:
                from backend.app.services.spine_connector import mirror_ops_project_to_spine
            spine_id = mirror_ops_project_to_spine(
                project_doc,
                client_name=project_doc.get("client_name"),
                source_id=str(result.inserted_id))
            if spine_id:
                self.projects.update_one(
                    {"_id": result.inserted_id},
                    {"$set": {"crm_project_id": spine_id}})
                project_doc["crm_project_id"] = spine_id
        except Exception:
            pass

        return self._serialize_project(project_doc)
    
    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Get a project by ID"""
        project = self.projects.find_one({"_id": ObjectId(project_id), "is_archived": False})
        return self._serialize_project(project) if project else None
    
    def list_projects(
        self,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        client_id: Optional[str] = None,
        project_lead_id: Optional[str] = None,
        include_archived: bool = False,
        skip: int = 0,
        limit: int = 50
    ) -> Dict[str, Any]:
        """List projects with filters"""
        query = {}
        
        if not include_archived:
            query["is_archived"] = False
        
        if status:
            query["status"] = status
        if priority:
            query["priority"] = priority
        if client_id:
            query["client_id"] = client_id
        if project_lead_id:
            query["project_lead_id"] = project_lead_id
        
        total = self.projects.count_documents(query)
        projects = list(self.projects.find(query).sort("created_at", -1).skip(skip).limit(limit))
        
        return {
            "items": [self._serialize_project(p) for p in projects],
            "total": total,
            "skip": skip,
            "limit": limit
        }
    
    def update_project(self, project_id: str, data: ProjectUpdate, updated_by: str = None) -> Optional[Dict[str, Any]]:
        """Update a project"""
        update_data = {k: v for k, v in data.model_dump().items() if v is not None}
        update_data["updated_at"] = datetime.utcnow()
        
        result = self.projects.find_one_and_update(
            {"_id": ObjectId(project_id), "is_archived": False},
            {"$set": update_data},
            return_document=True
        )
        
        return self._serialize_project(result) if result else None
    
    def update_project_status(self, project_id: str, status: ProjectStatus) -> Optional[Dict[str, Any]]:
        """Update project status"""
        update_data = {
            "status": status.value,
            "updated_at": datetime.utcnow()
        }
        
        if status == ProjectStatus.COMPLETED:
            update_data["actual_end_date"] = datetime.utcnow()
        
        result = self.projects.find_one_and_update(
            {"_id": ObjectId(project_id)},
            {"$set": update_data},
            return_document=True
        )
        
        return self._serialize_project(result) if result else None
    
    def archive_project(self, project_id: str) -> bool:
        """Archive a project"""
        result = self.projects.update_one(
            {"_id": ObjectId(project_id)},
            {"$set": {"is_archived": True, "archived_at": datetime.utcnow()}}
        )
        return result.modified_count > 0
    
    def delete_project(self, project_id: str) -> bool:
        """Permanently delete a project and all its tasks"""
        # Delete all tasks
        self.tasks.delete_many({"project_id": project_id})
        
        # Delete time entries
        self.time_entries.delete_many({"project_id": project_id})
        
        # Delete project
        result = self.projects.delete_one({"_id": ObjectId(project_id)})
        return result.deleted_count > 0
    
    # ==================== TEAM MANAGEMENT ====================
    
    def add_team_member(
        self,
        project_id: str,
        user_id: str,
        user_name: str,
        role: str = "member",
        hours_allocated: float = 0,
        assigned_by: str = None
    ) -> Optional[Dict[str, Any]]:
        """Add a team member to a project"""
        member = {
            "user_id": user_id,
            "user_name": user_name,
            "role": role,
            "hours_allocated": hours_allocated,
            "assigned_at": datetime.utcnow(),
            "assigned_by": assigned_by
        }
        
        result = self.projects.find_one_and_update(
            {"_id": ObjectId(project_id), "team_members.user_id": {"$ne": user_id}},
            {"$push": {"team_members": member}, "$set": {"updated_at": datetime.utcnow()}},
            return_document=True
        )
        
        return self._serialize_project(result) if result else None
    
    def remove_team_member(self, project_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Remove a team member from a project"""
        result = self.projects.find_one_and_update(
            {"_id": ObjectId(project_id)},
            {
                "$pull": {"team_members": {"user_id": user_id}},
                "$set": {"updated_at": datetime.utcnow()}
            },
            return_document=True
        )
        
        return self._serialize_project(result) if result else None
    
    # ==================== MILESTONES ====================
    
    def add_milestone(
        self,
        project_id: str,
        name: str,
        description: str = None,
        due_date: datetime = None,
        deliverables: List[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Add a milestone to a project"""
        milestone = {
            "id": str(uuid.uuid4()),
            "name": name,
            "description": description,
            "due_date": due_date,
            "status": MilestoneStatus.PENDING.value,
            "deliverables": deliverables or []
        }
        
        result = self.projects.find_one_and_update(
            {"_id": ObjectId(project_id)},
            {"$push": {"milestones": milestone}, "$set": {"updated_at": datetime.utcnow()}},
            return_document=True
        )
        
        return self._serialize_project(result) if result else None
    
    def update_milestone(
        self,
        project_id: str,
        milestone_id: str,
        status: MilestoneStatus = None,
        name: str = None,
        due_date: datetime = None
    ) -> Optional[Dict[str, Any]]:
        """Update a milestone"""
        update = {}
        if status:
            update["milestones.$.status"] = status.value
            if status == MilestoneStatus.COMPLETED:
                update["milestones.$.completed_at"] = datetime.utcnow()
        if name:
            update["milestones.$.name"] = name
        if due_date:
            update["milestones.$.due_date"] = due_date
        
        update["updated_at"] = datetime.utcnow()
        
        result = self.projects.find_one_and_update(
            {"_id": ObjectId(project_id), "milestones.id": milestone_id},
            {"$set": update},
            return_document=True
        )
        
        return self._serialize_project(result) if result else None
    
    # ==================== TASKS ====================
    
    def create_task(self, data: TaskCreate, created_by: str = None) -> Dict[str, Any]:
        """Create a new task"""
        task_doc = {
            **data.model_dump(),
            "status": TaskStatus.TODO.value,
            "actual_hours": 0,
            "blocks": [],
            "created_at": datetime.utcnow(),
            "created_by": created_by
        }
        
        # Set assignment time if assigned
        if data.assigned_to:
            task_doc["assigned_at"] = datetime.utcnow()
            task_doc["assigned_by"] = created_by
        
        result = self.tasks.insert_one(task_doc)
        task_doc["_id"] = result.inserted_id
        
        # Update project task count
        self.projects.update_one(
            {"_id": ObjectId(data.project_id)},
            {"$inc": {"total_tasks": 1}}
        )
        
        return self._serialize_task(task_doc)
    
    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get a task by ID"""
        task = self.tasks.find_one({"_id": ObjectId(task_id)})
        return self._serialize_task(task) if task else None
    
    def list_tasks(
        self,
        project_id: str = None,
        status: str = None,
        priority: str = None,
        assigned_to: str = None,
        milestone_id: str = None,
        parent_task_id: str = None,
        skip: int = 0,
        limit: int = 100
    ) -> Dict[str, Any]:
        """List tasks with filters"""
        query = {}
        
        if project_id:
            query["project_id"] = project_id
        if status:
            query["status"] = status
        if priority:
            query["priority"] = priority
        if assigned_to:
            query["assigned_to"] = assigned_to
        if milestone_id:
            query["milestone_id"] = milestone_id
        if parent_task_id is not None:
            query["parent_task_id"] = parent_task_id if parent_task_id else None
        
        total = self.tasks.count_documents(query)
        tasks = list(self.tasks.find(query).sort([("priority", -1), ("due_date", 1)]).skip(skip).limit(limit))
        
        return {
            "items": [self._serialize_task(t) for t in tasks],
            "total": total,
            "skip": skip,
            "limit": limit
        }
    
    def update_task(self, task_id: str, data: TaskUpdate, updated_by: str = None) -> Optional[Dict[str, Any]]:
        """Update a task"""
        update_data = {k: v for k, v in data.model_dump().items() if v is not None}
        update_data["updated_at"] = datetime.utcnow()
        
        # Track status changes
        if data.status:
            old_task = self.tasks.find_one({"_id": ObjectId(task_id)})
            if old_task:
                old_status = old_task.get("status")
                new_status = data.status.value if isinstance(data.status, TaskStatus) else data.status
                
                if new_status == TaskStatus.COMPLETED.value and old_status != TaskStatus.COMPLETED.value:
                    update_data["completed_at"] = datetime.utcnow()
                    # Update project completed tasks count
                    self.projects.update_one(
                        {"_id": ObjectId(old_task["project_id"])},
                        {"$inc": {"completed_tasks": 1}}
                    )
                    self._update_project_progress(old_task["project_id"])
        
        # Update assignment tracking
        if data.assigned_to:
            update_data["assigned_at"] = datetime.utcnow()
            update_data["assigned_by"] = updated_by
        
        result = self.tasks.find_one_and_update(
            {"_id": ObjectId(task_id)},
            {"$set": update_data},
            return_document=True
        )
        
        return self._serialize_task(result) if result else None
    
    def update_task_status(self, task_id: str, status: TaskStatus) -> Optional[Dict[str, Any]]:
        """Update task status"""
        return self.update_task(task_id, TaskUpdate(status=status))
    
    def delete_task(self, task_id: str) -> bool:
        """Delete a task"""
        task = self.tasks.find_one({"_id": ObjectId(task_id)})
        if not task:
            return False
        
        # Update project task counts
        was_completed = task.get("status") == TaskStatus.COMPLETED.value
        update = {"$inc": {"total_tasks": -1}}
        if was_completed:
            update["$inc"]["completed_tasks"] = -1
        
        self.projects.update_one({"_id": ObjectId(task["project_id"])}, update)
        
        # Delete task
        result = self.tasks.delete_one({"_id": ObjectId(task_id)})
        
        # Update project progress
        self._update_project_progress(task["project_id"])
        
        return result.deleted_count > 0
    
    def get_subtasks(self, parent_task_id: str) -> List[Dict[str, Any]]:
        """Get subtasks of a task"""
        subtasks = list(self.tasks.find({"parent_task_id": parent_task_id}))
        return [self._serialize_task(t) for t in subtasks]
    
    # ==================== TIME TRACKING ====================
    
    def log_time(
        self,
        task_id: str,
        user_id: str,
        hours: float,
        date: datetime = None,
        description: str = None,
        is_billable: bool = True,
        hourly_rate: float = 0
    ) -> Dict[str, Any]:
        """Log time entry for a task"""
        task = self.tasks.find_one({"_id": ObjectId(task_id)})
        if not task:
            raise ValueError("Task not found")
        
        entry = {
            "task_id": task_id,
            "project_id": task["project_id"],
            "user_id": user_id,
            "date": date or datetime.utcnow(),
            "hours": hours,
            "description": description,
            "is_billable": is_billable,
            "hourly_rate": hourly_rate,
            "created_at": datetime.utcnow()
        }
        
        result = self.time_entries.insert_one(entry)
        entry["_id"] = result.inserted_id
        
        # Update task actual hours
        self.tasks.update_one(
            {"_id": ObjectId(task_id)},
            {"$inc": {"actual_hours": hours}}
        )
        
        # Update project budget spent if billable
        if is_billable and hourly_rate > 0:
            spent = hours * hourly_rate
            self.projects.update_one(
                {"_id": ObjectId(task["project_id"])},
                {"$inc": {"budget_spent": spent}}
            )
        
        return self._serialize_time_entry(entry)
    
    def get_time_entries(
        self,
        project_id: str = None,
        task_id: str = None,
        user_id: str = None,
        start_date: datetime = None,
        end_date: datetime = None
    ) -> List[Dict[str, Any]]:
        """Get time entries with filters"""
        query = {}
        
        if project_id:
            query["project_id"] = project_id
        if task_id:
            query["task_id"] = task_id
        if user_id:
            query["user_id"] = user_id
        if start_date or end_date:
            query["date"] = {}
            if start_date:
                query["date"]["$gte"] = start_date
            if end_date:
                query["date"]["$lte"] = end_date
        
        entries = list(self.time_entries.find(query).sort("date", -1))
        return [self._serialize_time_entry(e) for e in entries]
    
    # ==================== STATISTICS ====================
    
    def get_project_stats(self, client_id: str = None) -> ProjectStats:
        """Get project statistics"""
        query = {"is_archived": False}
        if client_id:
            query["client_id"] = client_id
        
        projects = list(self.projects.find(query))
        
        stats = ProjectStats()
        stats.total_projects = len(projects)
        
        for p in projects:
            status = p.get("status")
            if status == ProjectStatus.ACTIVE.value:
                stats.active_projects += 1
            elif status == ProjectStatus.COMPLETED.value:
                stats.completed_projects += 1
            elif status == ProjectStatus.ON_HOLD.value:
                stats.on_hold_projects += 1
            
            stats.total_tasks += p.get("total_tasks", 0)
            stats.completed_tasks += p.get("completed_tasks", 0)
            stats.total_budget += p.get("budget", 0)
            stats.total_spent += p.get("budget_spent", 0)
            
            # Count by status
            stats.by_status[status] = stats.by_status.get(status, 0) + 1
            
            # Count by priority
            priority = p.get("priority")
            stats.by_priority[priority] = stats.by_priority.get(priority, 0) + 1
        
        # Count overdue tasks
        stats.overdue_tasks = self.tasks.count_documents({
            "status": {"$nin": [TaskStatus.COMPLETED.value, TaskStatus.CANCELLED.value]},
            "due_date": {"$lt": datetime.utcnow()}
        })
        
        return stats
    
    def get_my_tasks(self, user_id: str, include_completed: bool = False) -> List[Dict[str, Any]]:
        """Get tasks assigned to a user"""
        query = {"assigned_to": user_id}
        if not include_completed:
            query["status"] = {"$nin": [TaskStatus.COMPLETED.value, TaskStatus.CANCELLED.value]}
        
        tasks = list(self.tasks.find(query).sort([("due_date", 1), ("priority", -1)]))
        return [self._serialize_task(t) for t in tasks]
    
    # ==================== HELPERS ====================
    
    def _update_project_progress(self, project_id: str):
        """Recalculate project progress percentage"""
        project = self.projects.find_one({"_id": ObjectId(project_id)})
        if project:
            total = project.get("total_tasks", 0)
            completed = project.get("completed_tasks", 0)
            progress = int((completed / total * 100) if total > 0 else 0)
            
            self.projects.update_one(
                {"_id": ObjectId(project_id)},
                {"$set": {"progress_percent": progress}}
            )
    
    def _serialize_project(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Serialize a project document"""
        if not doc:
            return None
        doc["id"] = str(doc.pop("_id"))
        return doc
    
    def _serialize_task(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Serialize a task document"""
        if not doc:
            return None
        doc["id"] = str(doc.pop("_id"))
        return doc
    
    def _serialize_time_entry(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Serialize a time entry document"""
        if not doc:
            return None
        doc["id"] = str(doc.pop("_id"))
        return doc
