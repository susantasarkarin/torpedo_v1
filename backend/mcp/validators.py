# backend/mcp/validators.py
# Schema validation for MCP actions

from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
from bson import ObjectId

from .models import (
    EntityType,
    ActionType,
    ValidationResult,
    ActionPayload,
)


class ValidationError(Exception):
    """Custom validation error"""
    def __init__(self, message: str, field: Optional[str] = None):
        self.message = message
        self.field = field
        super().__init__(message)


class FieldValidator:
    """Validators for individual fields"""
    
    @staticmethod
    def required(value: Any, field_name: str) -> Optional[str]:
        """Check if field is present and not empty"""
        if value is None or (isinstance(value, str) and not value.strip()):
            return f"{field_name} is required"
        return None
    
    @staticmethod
    def string_length(value: str, field_name: str, min_len: int = 0, max_len: int = 1000) -> Optional[str]:
        """Validate string length"""
        if not isinstance(value, str):
            return f"{field_name} must be a string"
        if len(value) < min_len:
            return f"{field_name} must be at least {min_len} characters"
        if len(value) > max_len:
            return f"{field_name} must be at most {max_len} characters"
        return None
    
    @staticmethod
    def positive_number(value: Any, field_name: str) -> Optional[str]:
        """Validate positive number"""
        if not isinstance(value, (int, float)):
            return f"{field_name} must be a number"
        if value < 0:
            return f"{field_name} must be positive"
        return None
    
    @staticmethod
    def email(value: str, field_name: str) -> Optional[str]:
        """Basic email validation"""
        if not isinstance(value, str):
            return f"{field_name} must be a string"
        if "@" not in value or "." not in value:
            return f"{field_name} must be a valid email address"
        return None
    
    @staticmethod
    def object_id(value: str, field_name: str) -> Optional[str]:
        """Validate MongoDB ObjectId"""
        if not isinstance(value, str):
            return f"{field_name} must be a string"
        try:
            ObjectId(value)
            return None
        except Exception:
            return f"{field_name} must be a valid ID"
    
    @staticmethod
    def enum_value(value: Any, field_name: str, valid_values: List[Any]) -> Optional[str]:
        """Validate enum value"""
        if value not in valid_values:
            return f"{field_name} must be one of: {', '.join(str(v) for v in valid_values)}"
        return None
    
    @staticmethod
    def date_string(value: str, field_name: str) -> Optional[str]:
        """Validate date string (ISO format)"""
        if not isinstance(value, str):
            return f"{field_name} must be a date string"
        try:
            datetime.fromisoformat(value.replace('Z', '+00:00'))
            return None
        except ValueError:
            return f"{field_name} must be a valid ISO date"
    
    @staticmethod
    def list_of(value: Any, field_name: str, item_validator: Callable) -> Optional[str]:
        """Validate list items"""
        if not isinstance(value, list):
            return f"{field_name} must be a list"
        for i, item in enumerate(value):
            error = item_validator(item, f"{field_name}[{i}]")
            if error:
                return error
        return None


# Schema definitions for each entity type and action
ENTITY_SCHEMAS: Dict[str, Dict[str, Dict[str, Any]]] = {
    EntityType.INVOICE.value: {
        ActionType.CREATE.value: {
            "required": ["customer_id", "items"],
            "fields": {
                "customer_id": {"type": "object_id"},
                "items": {"type": "list", "min_items": 1},
                "due_date": {"type": "date", "optional": True},
                "notes": {"type": "string", "max_length": 5000, "optional": True},
            }
        },
        ActionType.UPDATE.value: {
            "required": [],
            "fields": {
                "status": {"type": "enum", "values": ["draft", "sent", "paid", "overdue", "cancelled"]},
                "notes": {"type": "string", "max_length": 5000, "optional": True},
            }
        },
        ActionType.DELETE.value: {
            "required": [],
            "fields": {}
        },
        ActionType.SEND.value: {
            "required": [],
            "fields": {
                "email_to": {"type": "email", "optional": True},
            }
        },
    },
    EntityType.BILL.value: {
        ActionType.CREATE.value: {
            "required": ["vendor_id", "items"],
            "fields": {
                "vendor_id": {"type": "object_id"},
                "items": {"type": "list", "min_items": 1},
                "due_date": {"type": "date", "optional": True},
            }
        },
        ActionType.UPDATE.value: {
            "required": [],
            "fields": {
                "status": {"type": "enum", "values": ["pending", "approved", "paid", "overdue"]},
            }
        },
        ActionType.APPROVE.value: {
            "required": [],
            "fields": {
                "comment": {"type": "string", "optional": True},
            }
        },
    },
    EntityType.LEAD.value: {
        ActionType.CREATE.value: {
            "required": ["email"],
            "fields": {
                "email": {"type": "email"},
                "name": {"type": "string", "max_length": 200},
                "company": {"type": "string", "max_length": 200, "optional": True},
                "phone": {"type": "string", "max_length": 50, "optional": True},
                "source": {"type": "string", "optional": True},
            }
        },
        ActionType.UPDATE.value: {
            "required": [],
            "fields": {
                "status": {"type": "enum", "values": ["new", "contacted", "qualified", "unqualified", "converted"]},
                "assigned_to": {"type": "object_id", "optional": True},
            }
        },
        ActionType.CONVERT.value: {
            "required": [],
            "fields": {
                "create_contact": {"type": "boolean", "optional": True},
                "create_deal": {"type": "boolean", "optional": True},
                "deal_value": {"type": "number", "optional": True},
            }
        },
        ActionType.ASSIGN.value: {
            "required": ["assigned_to"],
            "fields": {
                "assigned_to": {"type": "object_id"},
            }
        },
    },
    EntityType.DEAL.value: {
        ActionType.CREATE.value: {
            "required": ["name", "contact_id"],
            "fields": {
                "name": {"type": "string", "max_length": 300},
                "contact_id": {"type": "object_id"},
                "value": {"type": "number"},
                "stage": {"type": "enum", "values": ["prospect", "qualified", "proposal", "negotiation", "closed_won", "closed_lost"]},
            }
        },
        ActionType.UPDATE.value: {
            "required": [],
            "fields": {
                "stage": {"type": "enum", "values": ["prospect", "qualified", "proposal", "negotiation", "closed_won", "closed_lost"]},
                "value": {"type": "number", "optional": True},
            }
        },
    },
    EntityType.PROJECT.value: {
        ActionType.CREATE.value: {
            "required": ["name"],
            "fields": {
                "name": {"type": "string", "max_length": 300},
                "description": {"type": "string", "max_length": 5000, "optional": True},
                "client_id": {"type": "object_id", "optional": True},
                "start_date": {"type": "date", "optional": True},
                "end_date": {"type": "date", "optional": True},
            }
        },
        ActionType.UPDATE.value: {
            "required": [],
            "fields": {
                "status": {"type": "enum", "values": ["planning", "active", "on_hold", "completed", "cancelled"]},
            }
        },
        ActionType.ASSIGN.value: {
            "required": ["team_members"],
            "fields": {
                "team_members": {"type": "list"},
            }
        },
    },
    EntityType.TICKET.value: {
        ActionType.CREATE.value: {
            "required": ["subject", "description"],
            "fields": {
                "subject": {"type": "string", "max_length": 300},
                "description": {"type": "string", "max_length": 10000},
                "priority": {"type": "enum", "values": ["low", "medium", "high", "urgent"]},
                "contact_id": {"type": "object_id", "optional": True},
            }
        },
        ActionType.UPDATE.value: {
            "required": [],
            "fields": {
                "status": {"type": "enum", "values": ["open", "in_progress", "waiting", "resolved", "closed"]},
                "priority": {"type": "enum", "values": ["low", "medium", "high", "urgent"]},
            }
        },
        ActionType.ASSIGN.value: {
            "required": ["assigned_to"],
            "fields": {
                "assigned_to": {"type": "object_id"},
            }
        },
    },
}


class ActionValidator:
    """Validates MCP action payloads against schemas"""
    
    def __init__(self):
        self.schemas = ENTITY_SCHEMAS
    
    def validate(self, payload: ActionPayload) -> ValidationResult:
        """Validate an action payload"""
        errors: List[str] = []
        warnings: List[str] = []
        transformed_data = dict(payload.data)
        
        entity_type = payload.entity_type.value
        action_type = payload.action_type.value
        
        # Check if schema exists
        if entity_type not in self.schemas:
            errors.append(f"Unknown entity type: {entity_type}")
            return ValidationResult(is_valid=False, errors=errors)
        
        entity_schemas = self.schemas[entity_type]
        if action_type not in entity_schemas:
            errors.append(f"Action '{action_type}' not supported for {entity_type}")
            return ValidationResult(is_valid=False, errors=errors)
        
        schema = entity_schemas[action_type]
        
        # Check required fields
        for field in schema.get("required", []):
            if field not in payload.data or payload.data[field] is None:
                errors.append(f"Missing required field: {field}")
        
        # Validate entity_id for non-create actions
        if action_type != ActionType.CREATE.value:
            if not payload.entity_id:
                errors.append("entity_id is required for this action")
            else:
                error = FieldValidator.object_id(payload.entity_id, "entity_id")
                if error:
                    errors.append(error)
        
        # Validate field types
        for field_name, field_config in schema.get("fields", {}).items():
            if field_name not in payload.data:
                if not field_config.get("optional", False) and field_name in schema.get("required", []):
                    continue  # Already reported as missing required
                continue
            
            value = payload.data[field_name]
            field_type = field_config.get("type")
            
            error = self._validate_field(field_name, value, field_config)
            if error:
                errors.append(error)
        
        # Check for unknown fields (warning only)
        known_fields = set(schema.get("fields", {}).keys())
        for field in payload.data:
            if field not in known_fields and known_fields:
                warnings.append(f"Unknown field '{field}' will be ignored")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            transformed_payload=transformed_data if len(errors) == 0 else None,
        )
    
    def _validate_field(self, field_name: str, value: Any, config: Dict[str, Any]) -> Optional[str]:
        """Validate a single field"""
        field_type = config.get("type")
        
        if value is None:
            if config.get("optional"):
                return None
            return f"{field_name} cannot be null"
        
        if field_type == "string":
            max_len = config.get("max_length", 1000)
            return FieldValidator.string_length(value, field_name, 0, max_len)
        
        elif field_type == "email":
            return FieldValidator.email(value, field_name)
        
        elif field_type == "object_id":
            return FieldValidator.object_id(value, field_name)
        
        elif field_type == "number":
            return FieldValidator.positive_number(value, field_name)
        
        elif field_type == "date":
            return FieldValidator.date_string(value, field_name)
        
        elif field_type == "enum":
            valid_values = config.get("values", [])
            return FieldValidator.enum_value(value, field_name, valid_values)
        
        elif field_type == "list":
            if not isinstance(value, list):
                return f"{field_name} must be a list"
            min_items = config.get("min_items", 0)
            if len(value) < min_items:
                return f"{field_name} must have at least {min_items} item(s)"
        
        elif field_type == "boolean":
            if not isinstance(value, bool):
                return f"{field_name} must be a boolean"
        
        return None
    
    def get_schema(self, entity_type: EntityType, action_type: ActionType) -> Optional[Dict[str, Any]]:
        """Get schema for an entity/action combination"""
        entity_schemas = self.schemas.get(entity_type.value, {})
        return entity_schemas.get(action_type.value)


# Singleton instance
_validator: Optional[ActionValidator] = None


def get_validator() -> ActionValidator:
    """Get or create validator instance"""
    global _validator
    if _validator is None:
        _validator = ActionValidator()
    return _validator
