"""
Basic tests for AI Cold Outreach & Re-Engagement Module
"""

import pytest
import sys
import os
from datetime import datetime
from bson import ObjectId

# Ensure backend/ directory is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import models
from outreach.models import (
    OutreachLead,
    PersonalizationLevel,
    EngagementStatus,
    SequenceStage,
    EmailStatus,
    SeniorityLevel,
    Department
)

# Import engines
from outreach.personalization import PersonalizationEngine
from outreach.templates import COLD_OUTREACH_TEMPLATES, BEHAVIOR_VARIANTS


class TestModels:
    """Test data models"""
    
    def test_outreach_lead_creation(self):
        """Test creating an outreach lead"""
        lead = OutreachLead(
            first_name="John",
            last_name="Doe",
            email="john.doe@example.com",
            company="Acme Corp",
            title="VP of Engineering",
            seniority=SeniorityLevel.VP,
            department=Department.ENGINEERING,
            industry="Technology",
            pain_point="Scaling infrastructure challenges"
        )
        
        assert lead.first_name == "John"
        assert lead.last_name == "Doe"
        assert lead.email == "john.doe@example.com"
        assert lead.company == "Acme Corp"
        assert lead.engagement_status == EngagementStatus.NEVER_OPENED
        assert lead.sequence_stage == SequenceStage.NOT_STARTED
        assert lead.emails_sent == 0
    
    def test_personalization_levels(self):
        """Test personalization level enum"""
        assert PersonalizationLevel.LIGHT.value == "Light"
        assert PersonalizationLevel.ROLE_BASED.value == "Role-Based"
        assert PersonalizationLevel.DEEP.value == "Deep"


class TestPersonalizationEngine:
    """Test personalization engine"""
    
    def test_extract_tokens(self):
        """Test token extraction from text"""
        engine = PersonalizationEngine()
        
        text = "Hi {{first_name}}, I work at {{company}} in {{industry}}"
        tokens = engine.extract_tokens(text)
        
        assert "first_name" in tokens
        assert "company" in tokens
        assert "industry" in tokens
        assert len(tokens) == 3
    
    def test_build_token_data(self):
        """Test building token replacement data"""
        engine = PersonalizationEngine()
        
        lead = OutreachLead(
            first_name="Jane",
            last_name="Smith",
            email="jane@test.com",
            company="TechCorp",
            industry="Software",
            title="Director of Product",
            seniority=SeniorityLevel.DIRECTOR,
            department=Department.PRODUCT,
            pain_point="Product market fit"
        )
        
        # Test Light level
        data_light = engine.build_token_data(lead, PersonalizationLevel.LIGHT)
        assert "first_name" in data_light
        assert "company" in data_light
        assert "industry" in data_light
        assert "pain_point" not in data_light  # Not available at Light level
        
        # Test Role-Based level
        data_role = engine.build_token_data(lead, PersonalizationLevel.ROLE_BASED)
        assert "first_name" in data_role
        assert "company" in data_role
        assert "industry" in data_role
        assert "title" in data_role
        assert "pain_point" in data_role
    
    def test_replace_tokens(self):
        """Test token replacement"""
        engine = PersonalizationEngine()
        
        text = "Hi {{first_name}}, we help {{company}} with {{pain_point}}"
        data = {
            "first_name": "John",
            "company": "Acme",
            "pain_point": "scaling challenges"
        }
        
        result = engine._replace_tokens(text, data)
        
        assert result == "Hi John, we help Acme with scaling challenges"
        assert "{{" not in result
        assert "}}" not in result


class TestTemplates:
    """Test email templates"""
    
    def test_cold_outreach_templates_exist(self):
        """Test that cold outreach templates are defined"""
        assert "email_1_introduction" in COLD_OUTREACH_TEMPLATES
        assert "email_2_value_followup" in COLD_OUTREACH_TEMPLATES
        assert "email_3_direct" in COLD_OUTREACH_TEMPLATES
        assert "email_4_final_touch" in COLD_OUTREACH_TEMPLATES
    
    def test_template_structure(self):
        """Test template has required fields"""
        template = COLD_OUTREACH_TEMPLATES["email_1_introduction"]
        
        assert "name" in template
        assert "subject" in template
        assert "body_html" in template
        assert "category" in template
        assert "required_tokens" in template
    
    def test_behavior_variants_exist(self):
        """Test behavior-based variants are defined"""
        assert "opened_no_reply" in BEHAVIOR_VARIANTS
        assert "not_opened" in BEHAVIOR_VARIANTS
        assert "clicked_no_reply" in BEHAVIOR_VARIANTS
        
        # Check variants structure
        opened_variants = BEHAVIOR_VARIANTS["opened_no_reply"]
        assert "subject_variants" in opened_variants
        assert "cta_variants" in opened_variants


class TestSequenceLogic:
    """Test sequence logic"""
    
    def test_sequence_stages(self):
        """Test sequence stage progression"""
        stages = [
            SequenceStage.NOT_STARTED,
            SequenceStage.EMAIL_1_SCHEDULED,
            SequenceStage.EMAIL_1_SENT,
            SequenceStage.EMAIL_2_SCHEDULED,
            SequenceStage.EMAIL_2_SENT,
            SequenceStage.EMAIL_3_SCHEDULED,
            SequenceStage.EMAIL_3_SENT,
            SequenceStage.EMAIL_4_SCHEDULED,
            SequenceStage.EMAIL_4_SENT,
            SequenceStage.SEQUENCE_COMPLETED
        ]
        
        # Test all stages are defined
        for stage in stages:
            assert stage.value is not None


class TestEngagementStatus:
    """Test engagement status"""
    
    def test_engagement_statuses(self):
        """Test all engagement statuses"""
        statuses = [
            EngagementStatus.NEVER_OPENED,
            EngagementStatus.OPENED_NO_REPLY,
            EngagementStatus.ENGAGED,
            EngagementStatus.REPLIED_POSITIVE,
            EngagementStatus.WARM_LEAD,
            EngagementStatus.BOUNCED,
            EngagementStatus.UNSUBSCRIBED
        ]
        
        for status in statuses:
            assert status.value is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
