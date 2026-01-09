"""
CLAY-LEVEL FEATURES: INTEGRATION EXAMPLES
==========================================

Quick-start examples for using Clay features in your application
"""

# ============== EXAMPLE 1: BUILD A LIST WITH PREVIEW ==============

async def example_build_list_with_preview():
    """
    Step 1: Build a list and preview results before import
    """
    import httpx
    
    campaign_id = "campaign_123"
    session_id = "your_session_token"
    
    async with httpx.AsyncClient() as client:
        # Step 1: Compile filters to query plan
        filters = {
            "conditions": [
                {
                    "field": "job_title",
                    "operator": "contains",
                    "value": "CEO"
                },
                {
                    "field": "company_size",
                    "operator": "gte",
                    "value": "100"
                }
            ],
            "logic": "AND"
        }
        
        compile_response = await client.post(
            "http://localhost:8000/leads/clay/filters/compile",
            json={"filter_group": filters},
            headers={"Authorization": session_id}
        )
        query_plan = compile_response.json()["query_plan"]
        
        # Step 2: Execute preview (dry-run)
        preview_response = await client.post(
            "http://localhost:8000/leads/clay/preview/execute",
            json={
                "campaign_id": campaign_id,
                "query_plan": query_plan,
                "primary_provider": "clay"
            },
            headers={"Authorization": session_id}
        )
        
        preview_data = preview_response.json()
        print(f"Preview returned: {preview_data['record_count']} records")
        print(f"Estimated cost: ${preview_data['estimated_cost']}")
        print(f"Schema: {preview_data['inferred_schema']}")
        
        # Step 3: Create import session (with dedup gate)
        import_response = await client.post(
            "http://localhost:8000/leads/clay/import/gate",
            json={
                "campaign_id": campaign_id,
                "source_records": preview_data["sample_records"],
                "deduplication_strategy": "email_exact"
            },
            headers={"Authorization": session_id}
        )
        
        session = import_response.json()["import_session"]
        print(f"New records: {session['new_records_count']}")
        print(f"Duplicates found: {session['duplicate_count']}")
        print(f"Total cost: ${session['estimated_cost']}")
        
        # Step 4: Approve import if cost is acceptable
        if session["estimated_cost"] < 500:  # Under $500
            approve_response = await client.post(
                "http://localhost:8000/leads/clay/import/approve",
                json={
                    "import_session_id": session["session_id"],
                    "user_approved_cost": session["estimated_cost"],
                    "cost_cap": 500
                },
                headers={"Authorization": session_id}
            )
            print(f"Import approved: {approve_response.json()['status']}")


# ============== EXAMPLE 2: CREATE A WORKBOOK & ENRICH ==============

async def example_create_workbook_and_enrich():
    """
    Step 2: Create a workbook, add enrichment columns, execute
    """
    import httpx
    
    campaign_id = "campaign_123"
    session_id = "your_session_token"
    
    async with httpx.AsyncClient() as client:
        # Step 1: Create workbook
        workbook_response = await client.post(
            "http://localhost:8000/leads/clay/workbooks",
            json={
                "campaign_id": campaign_id,
                "name": "CEO Enrichment Q1",
                "description": "Enrich CEOs with contact info and company data"
            },
            headers={"Authorization": session_id}
        )
        workbook = workbook_response.json()["workbook"]
        workbook_id = workbook["_id"]
        
        # Step 2: Add static import column
        col1_response = await client.post(
            f"http://localhost:8000/leads/clay/workbooks/{workbook_id}/columns",
            json={
                "name": "Email",
                "type": "static_field",
                "config": {
                    "source_field": "email",
                    "source_type": "csv_import"
                }
            },
            headers={"Authorization": session_id}
        )
        
        # Step 3: Add enrichment column (Apollo)
        col2_response = await client.post(
            f"http://localhost:8000/leads/clay/workbooks/{workbook_id}/columns",
            json={
                "name": "Phone (Apollo)",
                "type": "enrichment",
                "config": {
                    "provider": "apollo",
                    "fields": ["phone", "mobile_phone"],
                    "match_on": "email"
                }
            },
            headers={"Authorization": session_id}
        )
        
        # Step 4: Add enrichment column (Clearbit)
        col3_response = await client.post(
            f"http://localhost:8000/leads/clay/workbooks/{workbook_id}/columns",
            json={
                "name": "Company Data (Clearbit)",
                "type": "enrichment",
                "config": {
                    "provider": "clearbit",
                    "fields": ["company_size", "industry", "funding"],
                    "match_on": "company_name"
                }
            },
            headers={"Authorization": session_id}
        )
        
        # Step 5: Execute first enrichment column
        exec_response = await client.post(
            f"http://localhost:8000/leads/clay/workbooks/{workbook_id}/columns/1/execute",
            json={
                "rows": list(range(0, 50))  # Execute first 50 rows
            },
            headers={"Authorization": session_id}
        )
        
        result = exec_response.json()
        print(f"Executed {result['rows_processed']} rows")
        print(f"Cost: ${result['cost_incurred']}")
        print(f"Success rate: {result['success_count']}/{result['total_count']}")


# ============== EXAMPLE 3: SYNC WORKBOOK BACK TO CAMPAIGN ==============

async def example_sync_workbook_to_campaign():
    """
    Step 3: Sync completed workbook rows back to campaign
    """
    import httpx
    from leads.campaign_integration import get_campaign_integration
    
    campaign_id = "campaign_123"
    workbook_id = "workbook_456"
    completed_row_ids = [0, 1, 2, 3, 4, 5]  # Row indices
    
    integration = get_campaign_integration()
    
    # Sync rows back to campaign (dedup handled automatically)
    result = await integration.sync_leads_to_campaign(
        campaign_id=campaign_id,
        workbook_id=workbook_id,
        row_ids=completed_row_ids,
        action="attach"  # or "update", "replace"
    )
    
    print(f"Synced {result['leads_synced']} leads to campaign")
    print(f"Duplicates found: {result['duplicates_found']}")


# ============== EXAMPLE 4: MANUAL CELL OVERRIDE ==============

async def example_override_cell():
    """
    Step 4: Manually override a cell value (e.g., correct bad data)
    """
    import httpx
    
    campaign_id = "campaign_123"
    workbook_id = "workbook_456"
    row_index = 5
    column_id = 2
    session_id = "your_session_token"
    
    async with httpx.AsyncClient() as client:
        # Set manual override for a cell
        override_response = await client.post(
            f"http://localhost:8000/leads/clay/workbooks/{workbook_id}/cells/{row_index}/{column_id}/override",
            json={
                "manual_value": "+1-555-1234",
                "note": "Corrected phone number from LinkedIn"
            },
            headers={"Authorization": session_id}
        )
        
        result = override_response.json()
        print(f"Cell overridden: {result['status']}")
        print(f"Previous value: {result['previous_value']}")
        print(f"New value: {result['manual_value']}")


# ============== EXAMPLE 5: MULTI-STEP WORKFLOW ==============

async def example_multi_step_workflow():
    """
    Step 5: Create a multi-step workflow (find, enrich, score)
    """
    import httpx
    from leads.workflow_engine import WorkflowDAG, WorkflowTask, WorkflowExecutor
    from leads.clay_models import SourceProvider
    
    # Create workflow DAG
    dag = WorkflowDAG("workflow_find_enrich_score")
    
    # Task 1: Find contacts
    find_task = WorkflowTask(
        task_id="step_1",
        name="Find Contacts",
        task_type="search",
        config={
            "provider": SourceProvider.CLAY,
            "query_plan": {
                "filters": [
                    {"field": "job_title", "operator": "contains", "value": "CEO"}
                ]
            }
        },
        continue_on_failure=False
    )
    dag.add_task(find_task)
    
    # Task 2: Enrich (depends on Task 1)
    enrich_task = WorkflowTask(
        task_id="step_2",
        name="Enrich",
        task_type="enrichment",
        config={
            "provider": SourceProvider.APOLLO,
            "fields": ["phone", "email"]
        },
        dependencies=["step_1"],
        continue_on_failure=True  # Non-blocking
    )
    dag.add_task(enrich_task)
    
    # Task 3: Score (depends on Task 2)
    score_task = WorkflowTask(
        task_id="step_3",
        name="Score",
        task_type="ai_transform",
        config={
            "model": "gpt-4",
            "prompt": "Score lead quality 0-100"
        },
        dependencies=["step_2"]
    )
    dag.add_task(score_task)
    
    # Execute workflow
    executor = WorkflowExecutor()
    result_dag = await executor.execute_workflow(
        dag,
        max_concurrent_tasks=2
    )
    
    print(f"Workflow status: {result_dag.status}")
    for task_id, task in result_dag.tasks.items():
        print(f"  {task_id}: {task.status} ({task.retries} retries)")


# ============== EXAMPLE 6: COST TRACKING & BUDGET ==============

async def example_check_budget():
    """
    Step 6: Check cost budget and remaining funds
    """
    import httpx
    
    campaign_id = "campaign_123"
    session_id = "your_session_token"
    
    async with httpx.AsyncClient() as client:
        # Get cost summary
        cost_response = await client.get(
            f"http://localhost:8000/leads/clay/workbooks?campaign_id={campaign_id}&summary=true",
            headers={"Authorization": session_id}
        )
        
        summary = cost_response.json()["cost_summary"]
        print(f"Total cost (month): ${summary['total_cost']}")
        print(f"Daily limit: ${summary['daily_hard_cap']}")
        print(f"Monthly limit: ${summary['monthly_hard_cap']}")
        print(f"Remaining budget: ${summary['remaining_budget']}")
        
        # Set new budget limits
        config_response = await client.post(
            "http://localhost:8000/leads/clay/cost-control",
            json={
                "campaign_id": campaign_id,
                "daily_hard_cap": 500.0,
                "monthly_hard_cap": 5000.0,
                "kill_switch": False
            },
            headers={"Authorization": session_id}
        )
        
        print(f"Budget updated: {config_response.json()['status']}")


# ============== EXAMPLE 7: ATTACH CLAY TO CAMPAIGN ==============

async def example_attach_clay_to_campaign():
    """
    Step 0: Set up Clay for an existing campaign
    """
    from leads.campaign_integration import get_campaign_integration
    from leads.clay_models import CostControl, DeduplicationRule
    
    campaign_id = "campaign_123"
    integration = get_campaign_integration()
    
    # Attach Clay to campaign with custom config
    result = await integration.attach_clay_to_campaign(
        campaign_id=campaign_id,
        cost_control=CostControl(
            daily_hard_cap=1000.0,
            monthly_hard_cap=10000.0,
            cost_estimation_enabled=True
        ),
        dedup_rules=[
            DeduplicationRule(
                name="email_exact",
                strategy="exact",
                fields=["email"]
            ),
            DeduplicationRule(
                name="name_company",
                strategy="composite",
                fields=["first_name", "last_name", "company_name"]
            )
        ]
    )
    
    print(f"Clay enabled: {result['clay_enabled']}")
    print(f"Cost control: {result['config']['cost_control']}")


# ============== EXAMPLE 8: QUERY EXECUTION LOGS ==============

async def example_query_execution_logs():
    """
    Step 8: Audit trail - query execution history
    """
    import httpx
    
    campaign_id = "campaign_123"
    session_id = "your_session_token"
    
    async with httpx.AsyncClient() as client:
        # Get execution logs
        logs_response = await client.get(
            f"http://localhost:8000/leads/clay/execution-logs?campaign_id={campaign_id}&limit=100",
            headers={"Authorization": session_id}
        )
        
        logs = logs_response.json()["logs"]
        
        for log in logs:
            print(f"{log['created_at']}: {log['action']}")
            print(f"  Status: {log['status']}")
            print(f"  Cost: ${log['cost']}")
            if log.get("error"):
                print(f"  Error: {log['error']}")


if __name__ == "__main__":
    import asyncio
    
    # Run examples
    print("See individual functions for API usage examples")
    print("\nTo use:")
    print("1. example_build_list_with_preview() - Preview before import")
    print("2. example_create_workbook_and_enrich() - Create enrichment workbook")
    print("3. example_sync_workbook_to_campaign() - Sync back to campaign")
    print("4. example_override_cell() - Manual data correction")
    print("5. example_multi_step_workflow() - Multi-step campaigns")
    print("6. example_check_budget() - Monitor costs")
    print("7. example_attach_clay_to_campaign() - Enable Clay for campaign")
    print("8. example_query_execution_logs() - Audit trail")
