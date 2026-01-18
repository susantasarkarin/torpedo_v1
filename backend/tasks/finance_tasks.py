"""
Finance Celery Tasks
Background tasks for finance operations: imports, exports, reports
"""

import os
import csv
import io
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from backend.celery_app import celery_app
from backend.db_pools import get_background_db, get_background_collection

logger = logging.getLogger(__name__)


# ============== EXPORT TASKS ==============

@celery_app.task(
    bind=True,
    name='backend.tasks.finance_tasks.export_customers_csv',
    max_retries=2,
)
def export_customers_csv(self) -> Dict[str, Any]:
    """
    Export all customers to CSV in the background.
    Stores result in GridFS or returns as base64.
    """
    task_id = self.request.id
    
    try:
        customers_collection = get_background_collection('customers')
        
        # Update progress
        self.update_state(state='PROGRESS', meta={'stage': 'fetching_customers'})
        
        customers = list(customers_collection.find())
        total = len(customers)
        
        # Generate CSV
        output = io.StringIO()
        fieldnames = [
            'customer_number', 'display_name', 'contact_name', 'email',
            'phone', 'address', 'city', 'state', 'zip_code', 'country',
            'gst_number', 'currency', 'payment_terms', 'notes'
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        
        for i, customer in enumerate(customers):
            if i % 100 == 0:
                self.update_state(
                    state='PROGRESS',
                    meta={'stage': 'writing_csv', 'processed': i, 'total': total}
                )
            
            row = {field: customer.get(field, '') for field in fieldnames}
            writer.writerow(row)
        
        csv_content = output.getvalue()
        
        # Store in GridFS or temp collection
        exports_collection = get_background_collection('export_files')
        result = exports_collection.insert_one({
            'type': 'customers_csv',
            'content': csv_content,
            'row_count': total,
            'created_at': datetime.utcnow(),
            'task_id': task_id,
            'expires_at': datetime.utcnow() + timedelta(hours=24)
        })
        
        return {
            'status': 'success',
            'export_id': str(result.inserted_id),
            'row_count': total,
            'task_id': task_id
        }
        
    except Exception as e:
        logger.error(f"Error exporting customers: {e}")
        raise


@celery_app.task(
    bind=True,
    name='backend.tasks.finance_tasks.export_invoices_csv',
    max_retries=2,
)
def export_invoices_csv(
    self,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> Dict[str, Any]:
    """
    Export invoices to CSV with optional date filtering.
    """
    task_id = self.request.id
    
    try:
        invoices_collection = get_background_collection('invoices')
        customers_collection = get_background_collection('customers')
        
        # Build query
        query = {}
        if start_date:
            query['invoice_date'] = {'$gte': datetime.fromisoformat(start_date)}
        if end_date:
            if 'invoice_date' in query:
                query['invoice_date']['$lte'] = datetime.fromisoformat(end_date)
            else:
                query['invoice_date'] = {'$lte': datetime.fromisoformat(end_date)}
        
        self.update_state(state='PROGRESS', meta={'stage': 'fetching_invoices'})
        
        invoices = list(invoices_collection.find(query))
        total = len(invoices)
        
        # Build customer lookup
        customer_ids = list(set(inv.get('customer_id') for inv in invoices if inv.get('customer_id')))
        customers = {str(c['_id']): c for c in customers_collection.find({'_id': {'$in': customer_ids}})}
        
        # Generate CSV
        output = io.StringIO()
        fieldnames = [
            'invoice_number', 'customer_name', 'invoice_date', 'due_date',
            'subtotal', 'tax_amount', 'total_amount', 'status', 'paid_amount',
            'balance_due', 'currency', 'notes'
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        
        for i, inv in enumerate(invoices):
            if i % 100 == 0:
                self.update_state(
                    state='PROGRESS',
                    meta={'stage': 'writing_csv', 'processed': i, 'total': total}
                )
            
            customer = customers.get(str(inv.get('customer_id')), {})
            
            row = {
                'invoice_number': inv.get('invoice_number', ''),
                'customer_name': customer.get('display_name', ''),
                'invoice_date': inv.get('invoice_date', ''),
                'due_date': inv.get('due_date', ''),
                'subtotal': inv.get('subtotal', 0),
                'tax_amount': inv.get('tax_amount', 0),
                'total_amount': inv.get('total_amount', 0),
                'status': inv.get('status', ''),
                'paid_amount': inv.get('paid_amount', 0),
                'balance_due': inv.get('balance_due', 0),
                'currency': inv.get('currency', 'INR'),
                'notes': inv.get('notes', '')
            }
            writer.writerow(row)
        
        csv_content = output.getvalue()
        
        exports_collection = get_background_collection('export_files')
        result = exports_collection.insert_one({
            'type': 'invoices_csv',
            'content': csv_content,
            'row_count': total,
            'filters': {'start_date': start_date, 'end_date': end_date},
            'created_at': datetime.utcnow(),
            'task_id': task_id,
            'expires_at': datetime.utcnow() + timedelta(hours=24)
        })
        
        return {
            'status': 'success',
            'export_id': str(result.inserted_id),
            'row_count': total,
            'task_id': task_id
        }
        
    except Exception as e:
        logger.error(f"Error exporting invoices: {e}")
        raise


@celery_app.task(
    bind=True,
    name='backend.tasks.finance_tasks.export_bills_csv',
    max_retries=2,
)
def export_bills_csv(
    self,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> Dict[str, Any]:
    """Export bills to CSV with optional date filtering."""
    task_id = self.request.id
    
    try:
        bills_collection = get_background_collection('bills')
        vendors_collection = get_background_collection('vendors')
        
        query = {}
        if start_date:
            query['bill_date'] = {'$gte': datetime.fromisoformat(start_date)}
        if end_date:
            if 'bill_date' in query:
                query['bill_date']['$lte'] = datetime.fromisoformat(end_date)
            else:
                query['bill_date'] = {'$lte': datetime.fromisoformat(end_date)}
        
        self.update_state(state='PROGRESS', meta={'stage': 'fetching_bills'})
        
        bills = list(bills_collection.find(query))
        total = len(bills)
        
        # Build vendor lookup
        vendor_ids = list(set(b.get('vendor_id') for b in bills if b.get('vendor_id')))
        vendors = {str(v['_id']): v for v in vendors_collection.find({'_id': {'$in': vendor_ids}})}
        
        output = io.StringIO()
        fieldnames = [
            'bill_number', 'vendor_name', 'bill_date', 'due_date',
            'subtotal', 'tax_amount', 'total_amount', 'status',
            'paid_amount', 'balance_due', 'currency'
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        
        for i, bill in enumerate(bills):
            if i % 100 == 0:
                self.update_state(
                    state='PROGRESS',
                    meta={'stage': 'writing_csv', 'processed': i, 'total': total}
                )
            
            vendor = vendors.get(str(bill.get('vendor_id')), {})
            row = {
                'bill_number': bill.get('bill_number', ''),
                'vendor_name': vendor.get('display_name', ''),
                'bill_date': bill.get('bill_date', ''),
                'due_date': bill.get('due_date', ''),
                'subtotal': bill.get('subtotal', 0),
                'tax_amount': bill.get('tax_amount', 0),
                'total_amount': bill.get('total_amount', 0),
                'status': bill.get('status', ''),
                'paid_amount': bill.get('paid_amount', 0),
                'balance_due': bill.get('balance_due', 0),
                'currency': bill.get('currency', 'INR')
            }
            writer.writerow(row)
        
        csv_content = output.getvalue()
        
        exports_collection = get_background_collection('export_files')
        result = exports_collection.insert_one({
            'type': 'bills_csv',
            'content': csv_content,
            'row_count': total,
            'filters': {'start_date': start_date, 'end_date': end_date},
            'created_at': datetime.utcnow(),
            'task_id': task_id,
            'expires_at': datetime.utcnow() + timedelta(hours=24)
        })
        
        return {
            'status': 'success',
            'export_id': str(result.inserted_id),
            'row_count': total,
            'task_id': task_id
        }
        
    except Exception as e:
        logger.error(f"Error exporting bills: {e}")
        raise


# ============== IMPORT TASKS ==============

@celery_app.task(
    bind=True,
    name='backend.tasks.finance_tasks.import_customers_csv',
    max_retries=1,
)
def import_customers_csv(self, csv_content: str) -> Dict[str, Any]:
    """
    Import customers from CSV content.
    """
    task_id = self.request.id
    
    try:
        customers_collection = get_background_collection('customers')
        
        self.update_state(state='PROGRESS', meta={'stage': 'parsing_csv'})
        
        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)
        total = len(rows)
        
        imported = 0
        skipped = 0
        errors = []
        
        for i, row in enumerate(rows):
            if i % 50 == 0:
                self.update_state(
                    state='PROGRESS',
                    meta={'stage': 'importing', 'processed': i, 'total': total}
                )
            
            try:
                # Validate required fields
                if not row.get('display_name'):
                    skipped += 1
                    errors.append(f"Row {i+1}: Missing display_name")
                    continue
                
                # Check for duplicate
                existing = customers_collection.find_one({
                    '$or': [
                        {'customer_number': row.get('customer_number')},
                        {'email': row.get('email')}
                    ]
                })
                
                if existing:
                    skipped += 1
                    continue
                
                # Insert customer
                customer_doc = {
                    'customer_number': row.get('customer_number', f"CUST-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{i}"),
                    'display_name': row.get('display_name'),
                    'contact_name': row.get('contact_name', ''),
                    'email': row.get('email', ''),
                    'phone': row.get('phone', ''),
                    'address': row.get('address', ''),
                    'city': row.get('city', ''),
                    'state': row.get('state', ''),
                    'zip_code': row.get('zip_code', ''),
                    'country': row.get('country', 'India'),
                    'gst_number': row.get('gst_number', ''),
                    'currency': row.get('currency', 'INR'),
                    'payment_terms': row.get('payment_terms', 'Net 30'),
                    'notes': row.get('notes', ''),
                    'created_at': datetime.utcnow(),
                    'imported_via': 'csv',
                    'import_task_id': task_id
                }
                
                customers_collection.insert_one(customer_doc)
                imported += 1
                
            except Exception as e:
                errors.append(f"Row {i+1}: {str(e)}")
        
        return {
            'status': 'success',
            'total_rows': total,
            'imported': imported,
            'skipped': skipped,
            'errors': errors[:50],  # Limit error messages
            'task_id': task_id
        }
        
    except Exception as e:
        logger.error(f"Error importing customers: {e}")
        raise


@celery_app.task(
    bind=True,
    name='backend.tasks.finance_tasks.import_invoices_csv',
    max_retries=1,
)
def import_invoices_csv(self, csv_content: str) -> Dict[str, Any]:
    """Import invoices from CSV content."""
    task_id = self.request.id
    
    try:
        invoices_collection = get_background_collection('invoices')
        customers_collection = get_background_collection('customers')
        
        self.update_state(state='PROGRESS', meta={'stage': 'parsing_csv'})
        
        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)
        total = len(rows)
        
        # Build customer lookup by name/email
        all_customers = list(customers_collection.find({}, {'_id': 1, 'display_name': 1, 'email': 1}))
        customer_lookup = {}
        for c in all_customers:
            if c.get('display_name'):
                customer_lookup[c['display_name'].lower()] = str(c['_id'])
            if c.get('email'):
                customer_lookup[c['email'].lower()] = str(c['_id'])
        
        imported = 0
        skipped = 0
        errors = []
        
        for i, row in enumerate(rows):
            if i % 50 == 0:
                self.update_state(
                    state='PROGRESS',
                    meta={'stage': 'importing', 'processed': i, 'total': total}
                )
            
            try:
                # Find customer
                customer_name = row.get('customer_name', '').lower()
                customer_id = customer_lookup.get(customer_name)
                
                if not customer_id:
                    skipped += 1
                    errors.append(f"Row {i+1}: Customer not found: {row.get('customer_name')}")
                    continue
                
                # Check duplicate invoice number
                if row.get('invoice_number'):
                    existing = invoices_collection.find_one({'invoice_number': row['invoice_number']})
                    if existing:
                        skipped += 1
                        continue
                
                invoice_doc = {
                    'invoice_number': row.get('invoice_number', f"INV-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{i}"),
                    'customer_id': customer_id,
                    'invoice_date': row.get('invoice_date'),
                    'due_date': row.get('due_date'),
                    'subtotal': float(row.get('subtotal', 0) or 0),
                    'tax_amount': float(row.get('tax_amount', 0) or 0),
                    'total_amount': float(row.get('total_amount', 0) or 0),
                    'status': row.get('status', 'draft'),
                    'paid_amount': float(row.get('paid_amount', 0) or 0),
                    'currency': row.get('currency', 'INR'),
                    'notes': row.get('notes', ''),
                    'created_at': datetime.utcnow(),
                    'imported_via': 'csv',
                    'import_task_id': task_id
                }
                invoice_doc['balance_due'] = invoice_doc['total_amount'] - invoice_doc['paid_amount']
                
                invoices_collection.insert_one(invoice_doc)
                imported += 1
                
            except Exception as e:
                errors.append(f"Row {i+1}: {str(e)}")
        
        return {
            'status': 'success',
            'total_rows': total,
            'imported': imported,
            'skipped': skipped,
            'errors': errors[:50],
            'task_id': task_id
        }
        
    except Exception as e:
        logger.error(f"Error importing invoices: {e}")
        raise


# ============== REPORT TASKS ==============

@celery_app.task(
    bind=True,
    name='backend.tasks.finance_tasks.generate_finance_summary',
    max_retries=2,
)
def generate_finance_summary(
    self,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate comprehensive finance summary report.
    Heavy aggregation across multiple collections.
    """
    task_id = self.request.id
    
    try:
        invoices_coll = get_background_collection('invoices')
        bills_coll = get_background_collection('bills')
        expenses_coll = get_background_collection('expenses')
        payments_received_coll = get_background_collection('payments_received')
        payments_made_coll = get_background_collection('payments_made')
        
        # Build date filter
        date_filter = {}
        if start_date:
            date_filter['$gte'] = datetime.fromisoformat(start_date)
        if end_date:
            date_filter['$lte'] = datetime.fromisoformat(end_date)
        
        self.update_state(state='PROGRESS', meta={'stage': 'calculating_receivables'})
        
        # Accounts Receivable
        inv_query = {'invoice_date': date_filter} if date_filter else {}
        invoices = list(invoices_coll.find(inv_query))
        total_invoiced = sum(inv.get('total_amount', 0) for inv in invoices)
        total_received = sum(inv.get('paid_amount', 0) for inv in invoices)
        outstanding_ar = total_invoiced - total_received
        
        self.update_state(state='PROGRESS', meta={'stage': 'calculating_payables'})
        
        # Accounts Payable
        bill_query = {'bill_date': date_filter} if date_filter else {}
        bills = list(bills_coll.find(bill_query))
        total_billed = sum(b.get('total_amount', 0) for b in bills)
        total_paid_bills = sum(b.get('paid_amount', 0) for b in bills)
        outstanding_ap = total_billed - total_paid_bills
        
        self.update_state(state='PROGRESS', meta={'stage': 'calculating_expenses'})
        
        # Expenses
        exp_query = {'expense_date': date_filter} if date_filter else {}
        expenses = list(expenses_coll.find(exp_query))
        total_expenses = sum(e.get('amount', 0) for e in expenses)
        
        self.update_state(state='PROGRESS', meta={'stage': 'calculating_cash_flow'})
        
        # Cash Flow
        pr_query = {'payment_date': date_filter} if date_filter else {}
        payments_in = list(payments_received_coll.find(pr_query))
        total_cash_in = sum(p.get('amount', 0) for p in payments_in)
        
        pm_query = {'payment_date': date_filter} if date_filter else {}
        payments_out = list(payments_made_coll.find(pm_query))
        total_cash_out = sum(p.get('amount', 0) for p in payments_out)
        
        net_cash_flow = total_cash_in - total_cash_out
        
        self.update_state(state='PROGRESS', meta={'stage': 'calculating_metrics'})
        
        # Top customers by revenue
        customer_revenue = {}
        for inv in invoices:
            cust_id = str(inv.get('customer_id', 'unknown'))
            customer_revenue[cust_id] = customer_revenue.get(cust_id, 0) + inv.get('total_amount', 0)
        
        top_customers = sorted(customer_revenue.items(), key=lambda x: x[1], reverse=True)[:10]
        
        # Top vendors by spend
        vendor_spend = {}
        for bill in bills:
            vendor_id = str(bill.get('vendor_id', 'unknown'))
            vendor_spend[vendor_id] = vendor_spend.get(vendor_id, 0) + bill.get('total_amount', 0)
        
        top_vendors = sorted(vendor_spend.items(), key=lambda x: x[1], reverse=True)[:10]
        
        # Store report
        reports_collection = get_background_collection('finance_reports')
        report = {
            'type': 'finance_summary',
            'period': {'start': start_date, 'end': end_date},
            'generated_at': datetime.utcnow(),
            'task_id': task_id,
            'data': {
                'accounts_receivable': {
                    'total_invoiced': total_invoiced,
                    'total_received': total_received,
                    'outstanding': outstanding_ar,
                    'invoice_count': len(invoices)
                },
                'accounts_payable': {
                    'total_billed': total_billed,
                    'total_paid': total_paid_bills,
                    'outstanding': outstanding_ap,
                    'bill_count': len(bills)
                },
                'expenses': {
                    'total': total_expenses,
                    'count': len(expenses)
                },
                'cash_flow': {
                    'cash_in': total_cash_in,
                    'cash_out': total_cash_out,
                    'net': net_cash_flow
                },
                'top_customers': top_customers,
                'top_vendors': top_vendors
            }
        }
        
        result = reports_collection.insert_one(report)
        
        return {
            'status': 'success',
            'report_id': str(result.inserted_id),
            'summary': {
                'outstanding_ar': outstanding_ar,
                'outstanding_ap': outstanding_ap,
                'net_cash_flow': net_cash_flow,
                'total_expenses': total_expenses
            },
            'task_id': task_id
        }
        
    except Exception as e:
        logger.error(f"Error generating finance summary: {e}")
        raise


@celery_app.task(
    bind=True,
    name='backend.tasks.finance_tasks.bulk_delete_customers',
    max_retries=1,
)
def bulk_delete_customers(self, customer_ids: List[str]) -> Dict[str, Any]:
    """
    Bulk delete customers with dependency checking.
    """
    task_id = self.request.id
    
    try:
        from bson import ObjectId
        
        customers_coll = get_background_collection('customers')
        invoices_coll = get_background_collection('invoices')
        
        deleted = 0
        skipped = 0
        errors = []
        
        total = len(customer_ids)
        
        for i, cust_id in enumerate(customer_ids):
            if i % 20 == 0:
                self.update_state(
                    state='PROGRESS',
                    meta={'stage': 'deleting', 'processed': i, 'total': total}
                )
            
            try:
                # Check for related invoices
                invoice_count = invoices_coll.count_documents({'customer_id': cust_id})
                
                if invoice_count > 0:
                    skipped += 1
                    errors.append(f"{cust_id}: Has {invoice_count} invoices")
                    continue
                
                # Delete customer
                result = customers_coll.delete_one({'_id': ObjectId(cust_id)})
                if result.deleted_count > 0:
                    deleted += 1
                else:
                    skipped += 1
                    
            except Exception as e:
                errors.append(f"{cust_id}: {str(e)}")
        
        return {
            'status': 'success',
            'total': total,
            'deleted': deleted,
            'skipped': skipped,
            'errors': errors[:50],
            'task_id': task_id
        }
        
    except Exception as e:
        logger.error(f"Error bulk deleting customers: {e}")
        raise
