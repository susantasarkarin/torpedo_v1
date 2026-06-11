"""
Dynamic Content Generator
AI-powered email personalization and content generation
"""

import re
from typing import Dict, List, Optional
from datetime import datetime
import random

class DynamicContentGenerator:
    """
    Generates personalized email content based on lead data
    Supports conditional blocks, dynamic variables, and AI-generated paragraphs
    """
    
    def __init__(self, db):
        self.db = db
        
        # Content templates library
        self.value_props = {
            'efficiency': [
                "save {time_saved} hours per week on {pain_point}",
                "reduce {pain_point} time by {percentage}%",
                "streamline your {process} workflow"
            ],
            'growth': [
                "increase {metric} by {percentage}%",
                "scale your {area} operations",
                "grow your {department} without adding headcount"
            ],
            'cost': [
                "reduce {expense_type} costs by {percentage}%",
                "eliminate expensive {tool_type} subscriptions",
                "save ${amount} annually on {category}"
            ]
        }
        
        # Industry-specific hooks
        self.industry_hooks = {
            'Technology': "As a tech company, you understand the importance of automation...",
            'Finance': "In the financial sector, efficiency and compliance are critical...",
            'Healthcare': "Healthcare organizations need reliable solutions that...",
            'Retail': "Retail businesses must move fast to stay competitive...",
            'Manufacturing': "Manufacturing companies rely on streamlined operations..."
        }
        
        # Seniority-specific language
        self.seniority_language = {
            'C-Level': {
                'focus': ['ROI', 'strategic impact', 'competitive advantage', 'board-level metrics'],
                'tone': 'executive'
            },
            'VP': {
                'focus': ['departmental efficiency', 'team productivity', 'budget optimization'],
                'tone': 'strategic'
            },
            'Director': {
                'focus': ['process improvement', 'team performance', 'implementation'],
                'tone': 'operational'
            },
            'Manager': {
                'focus': ['daily operations', 'task management', 'team coordination'],
                'tone': 'tactical'
            }
        }
    
    def generate_content_block(self, template: str, lead: Dict, block_type: str = 'intro') -> str:
        """
        Generate a content block based on template and lead data
        
        Args:
            template: Template string with variables
            lead: Lead data dictionary
            block_type: Type of content block (intro, value_prop, pain_point, cta)
            
        Returns:
            Generated content string
        """
        if block_type == 'intro':
            return self._generate_intro_block(lead)
        elif block_type == 'value_prop':
            return self._generate_value_prop_block(lead)
        elif block_type == 'pain_point':
            return self._generate_pain_point_block(lead)
        elif block_type == 'social_proof':
            return self._generate_social_proof_block(lead)
        elif block_type == 'cta':
            return self._generate_cta_block(lead)
        else:
            return self._apply_template_variables(template, lead)
    
    def _generate_intro_block(self, lead: Dict) -> str:
        """Generate personalized intro paragraph"""
        first_name = lead.get('first_name', 'there')
        company = lead.get('company', 'your company')
        title = lead.get('title', 'your role')
        industry = lead.get('industry', 'your industry')
        
        intros = [
            f"Hi {first_name},\n\nI noticed {company} is in the {industry} space and thought you'd be interested in how companies like yours are solving [pain point].",
            
            f"Hi {first_name},\n\nAs {title} at {company}, you're probably dealing with [challenge]. I wanted to share how similar companies are addressing this.",
            
            f"{first_name},\n\nQuick question: Is {company} currently facing challenges with [pain point]? I work with {industry} companies to solve this exact issue.",
            
            f"Hi {first_name},\n\nI came across {company} while researching {industry} companies and wanted to reach out about [opportunity]."
        ]
        
        return random.choice(intros)
    
    def _generate_value_prop_block(self, lead: Dict) -> str:
        """Generate value proposition based on lead profile"""
        company_size = lead.get('company_size', '')
        seniority = lead.get('seniority', '')
        
        # Determine primary value proposition
        if seniority in ['C-Level', 'VP']:
            focus = 'ROI and strategic impact'
            value = "Our clients see an average 300% ROI in the first year by automating [process]. This translates to $[amount] in cost savings and [X] hours freed up for strategic work."
        else:
            focus = 'efficiency and productivity'
            value = "Teams using our solution save [X] hours per week on [task], allowing them to focus on high-impact work instead of manual processes."
        
        return value
    
    def _generate_pain_point_block(self, lead: Dict) -> str:
        """Generate pain point acknowledgment"""
        industry = lead.get('industry', 'your industry')
        
        pain_points = {
            'Technology': "Most tech companies struggle with scaling their operations without proportionally increasing costs. Manual processes that worked at 50 people become bottlenecks at 200.",
            'Finance': "Financial teams often spend 60% of their time on data entry and reconciliation instead of analysis and strategy.",
            'Healthcare': "Healthcare organizations face the dual challenge of maintaining compliance while improving patient care efficiency.",
            'Retail': "Retail businesses need to move fast, but manual inventory and customer management slow everything down."
        }
        
        return pain_points.get(industry, "Many companies in your space struggle with efficiency and scalability challenges.")
    
    def _generate_social_proof_block(self, lead: Dict) -> str:
        """Generate social proof relevant to lead"""
        industry = lead.get('industry', '')
        company_size = lead.get('company_size', '')
        
        return f"We work with companies like [Similar Company] in {industry} who have seen [specific result]. For example, [Client Name] reduced their [metric] by [X]% in just [timeframe]."
    
    def _generate_cta_block(self, lead: Dict) -> str:
        """Generate appropriate call-to-action"""
        seniority = lead.get('seniority', '')
        
        if seniority in ['C-Level', 'VP']:
            ctas = [
                "Would you be open to a brief conversation about how we could deliver similar results for your team?",
                "I'd love to show you how we're helping similar companies achieve [outcome]. Are you available for a quick call next week?",
                "Can I send over a brief case study from a company in your space?"
            ]
        else:
            ctas = [
                "Would a quick 15-minute demo be helpful to see if this could work for your team?",
                "I'd be happy to show you how this works. Are you free for a quick call this week?",
                "Want to see a quick walkthrough? I can show you the key features in 10 minutes."
            ]
        
        return random.choice(ctas)
    
    def _apply_template_variables(self, template: str, lead: Dict) -> str:
        """Replace variables in template with lead data"""
        # Find all {{variable}} patterns
        variables = re.findall(r'\{\{(\w+)\}\}', template)
        
        result = template
        for var in variables:
            value = lead.get(var, f'[{var}]')
            result = result.replace(f'{{{{{var}}}}}', str(value))
        
        return result
    
    def personalize_dynamically(self, email_template: str, lead: Dict) -> str:
        """
        Dynamically personalize entire email template
        
        Args:
            email_template: Email template with conditional blocks and variables
            lead: Lead data dictionary
            
        Returns:
            Fully personalized email
        """
        # Step 1: Process conditional blocks
        result = self._process_conditional_blocks(email_template, lead)
        
        # Step 2: Generate dynamic content blocks
        result = self._process_dynamic_blocks(result, lead)
        
        # Step 3: Replace simple variables
        result = self._replace_variables(result, lead)
        
        # Step 4: Apply smart formatting
        result = self._apply_formatting(result)
        
        return result
    
    def _process_conditional_blocks(self, template: str, lead: Dict) -> str:
        """Process conditional content blocks"""
        # Pattern: {% if condition %}content{% endif %}
        pattern = r'\{%\s*if\s+(\w+)\s*%\}(.*?)\{%\s*endif\s*%\}'
        
        def replace_conditional(match):
            condition = match.group(1)
            content = match.group(2)
            
            # Check if condition is met
            if lead.get(condition):
                return content
            return ''
        
        return re.sub(pattern, replace_conditional, template, flags=re.DOTALL)
    
    def _process_dynamic_blocks(self, template: str, lead: Dict) -> str:
        """Process dynamic content generation blocks"""
        # Pattern: {% generate block_type %}
        pattern = r'\{%\s*generate\s+(\w+)\s*%\}'
        
        def replace_dynamic(match):
            block_type = match.group(1)
            return self.generate_content_block('', lead, block_type)
        
        return re.sub(pattern, replace_dynamic, template)
    
    def _replace_variables(self, template: str, lead: Dict) -> str:
        """Replace all {{variable}} patterns with lead data"""
        # Basic variables
        replacements = {
            'first_name': lead.get('first_name', 'there'),
            'last_name': lead.get('last_name', ''),
            'company': lead.get('company', 'your company'),
            'title': lead.get('title', 'your role'),
            'industry': lead.get('industry', 'your industry'),
            'seniority': lead.get('seniority', ''),
            'company_size': lead.get('company_size', '')
        }
        
        result = template
        for key, value in replacements.items():
            result = result.replace(f'{{{{{key}}}}}', str(value))
        
        return result
    
    def _apply_formatting(self, text: str) -> str:
        """Apply smart formatting rules"""
        # Remove extra whitespace
        text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
        
        # Ensure proper spacing after periods
        text = re.sub(r'\.(\S)', r'. \1', text)
        
        # Remove leading/trailing whitespace
        text = text.strip()
        
        return text
    
    def generate_subject_line(self, lead: Dict, variant: str = 'question') -> str:
        """
        Generate personalized subject line
        
        Args:
            lead: Lead data
            variant: Subject line variant (question, value, curiosity, social_proof)
            
        Returns:
            Subject line string
        """
        first_name = lead.get('first_name', 'there')
        company = lead.get('company', 'your company')
        
        if variant == 'question':
            subjects = [
                f"Quick question about {company}'s [process]",
                f"{first_name}, dealing with [pain point]?",
                f"Is {company} currently [challenge]?"
            ]
        elif variant == 'value':
            subjects = [
                f"Save [X] hours per week at {company}",
                f"{company} + [benefit]",
                f"How {company} can [achieve outcome]"
            ]
        elif variant == 'curiosity':
            subjects = [
                f"Thought about {company}",
                f"An idea for {first_name}",
                f"Re: {company}'s [area]"
            ]
        elif variant == 'social_proof':
            subjects = [
                f"How [Similar Company] achieved [result]",
                f"{first_name}, seeing this in [industry]?",
                f"[Client] reduced [metric] by [X]%"
            ]
        else:
            subjects = [
                f"Hi {first_name}",
                f"{company} - [topic]",
                f"Quick note for {first_name}"
            ]
        
        return random.choice(subjects)
    
    def generate_follow_up(self, lead: Dict, previous_email: str, sequence_step: int) -> str:
        """
        Generate contextual follow-up email
        
        Args:
            lead: Lead data
            previous_email: Content of previous email
            sequence_step: Which step in sequence (1, 2, 3, etc.)
            
        Returns:
            Follow-up email content
        """
        first_name = lead.get('first_name', 'there')
        
        if sequence_step == 1:
            # Gentle bump
            return f"Hi {first_name},\n\nJust wanted to make sure my last email didn't get buried. Still curious if [pain point] is something you're dealing with?\n\nLet me know if you'd like to chat."
        
        elif sequence_step == 2:
            # Value-add follow-up
            return f"{first_name},\n\nI came across this [resource] that's relevant to [challenge] and thought of you.\n\n[Resource description]\n\nWould this be helpful for {lead.get('company', 'your team')}?"
        
        elif sequence_step == 3:
            # Break-up email
            return f"Hi {first_name},\n\nI'll assume the timing isn't right for this. If things change or you'd like to revisit this conversation down the road, just let me know.\n\nBest,\n[Sender]"
        
        else:
            return f"Hi {first_name},\n\nFollowing up on my previous email. Let me know if you'd like to discuss [topic]."
    
    def create_ab_test_variants(self, base_template: str, lead: Dict, num_variants: int = 2) -> List[Dict]:
        """
        Create A/B test variants of email
        
        Args:
            base_template: Base email template
            lead: Lead data
            num_variants: Number of variants to create
            
        Returns:
            List of variant dictionaries
        """
        variants = []
        
        # Variant A: Original
        variants.append({
            'variant': 'A',
            'subject': self.generate_subject_line(lead, 'question'),
            'body': self.personalize_dynamically(base_template, lead)
        })
        
        # Variant B: Different subject + shorter body
        if num_variants >= 2:
            variants.append({
                'variant': 'B',
                'subject': self.generate_subject_line(lead, 'value'),
                'body': self._shorten_email(self.personalize_dynamically(base_template, lead))
            })
        
        # Variant C: Different approach
        if num_variants >= 3:
            variants.append({
                'variant': 'C',
                'subject': self.generate_subject_line(lead, 'curiosity'),
                'body': self._rewrite_conversational(self.personalize_dynamically(base_template, lead))
            })
        
        return variants[:num_variants]
    
    def _shorten_email(self, email: str) -> str:
        """Shorten email to key points"""
        # Split into paragraphs
        paragraphs = email.split('\n\n')
        
        # Keep first and last paragraphs, summarize middle
        if len(paragraphs) > 3:
            return '\n\n'.join([paragraphs[0], paragraphs[-1]])
        
        return email
    
    def _rewrite_conversational(self, email: str) -> str:
        """Make email more conversational"""
        # This would use an LLM in production
        # For now, return modified version
        return email.replace('I am writing', "I'm reaching out").replace('We would', "We'd").replace('I would', "I'd")


class DynamicContentService:
    """Service layer for dynamic content generation"""
    
    def __init__(self, db):
        self.db = db
        self.generator = DynamicContentGenerator(db)
    
    async def generate_campaign_emails(self, campaign_id: str, leads: List[Dict]) -> List[Dict]:
        """
        Generate personalized emails for all leads in campaign
        
        Args:
            campaign_id: Campaign ID
            leads: List of lead dictionaries
            
        Returns:
            List of generated emails
        """
        # Fetch campaign template
        campaign = await self.db.campaigns.find_one({'_id': campaign_id})
        template = campaign.get('email_template', '')
        
        generated_emails = []
        
        for lead in leads:
            email = {
                'lead_id': str(lead.get('_id')),
                'subject': self.generator.generate_subject_line(lead),
                'body': self.generator.personalize_dynamically(template, lead),
                'generated_at': datetime.now().isoformat()
            }
            generated_emails.append(email)
        
        return generated_emails
    
    async def generate_ab_test_campaign(self, campaign_id: str, num_variants: int = 2) -> Dict:
        """
        Generate A/B test variants for campaign
        
        Args:
            campaign_id: Campaign ID
            num_variants: Number of variants
            
        Returns:
            A/B test configuration
        """
        campaign = await self.db.campaigns.find_one({'_id': campaign_id})
        template = campaign.get('email_template', '')
        
        # Get sample lead for testing
        sample_lead = await self.db.leads.find_one({'campaign_id': campaign_id})
        
        variants = self.generator.create_ab_test_variants(template, sample_lead, num_variants)
        
        return {
            'campaign_id': campaign_id,
            'variants': variants,
            'split_percentage': 100 // num_variants,
            'created_at': datetime.now().isoformat()
        }
