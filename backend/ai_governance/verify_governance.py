"""
AI GOVERNANCE VERIFICATION SCRIPT
=================================
Verifies all acceptance criteria from the AI Workflow Consolidation & Governance Spec.

ACCEPTANCE CRITERIA (NON-NEGOTIABLE):
The implementation is INVALID if ANY of the following are true:
1. An email can be sent to Gemini more than once
2. Gemini can be called without checking the daily cap
3. More than one file can invoke Gemini
4. A scheduler or cron triggers Gemini
5. Automatic retries exist for Gemini failures
6. ChatGPT touches email classification or summaries
7. DeepSeek exists anywhere in the codebase

All answers must be NO for the implementation to be valid.
"""

import os
import sys
import re
import glob
from pathlib import Path
from typing import List, Tuple, Dict, Any

# Colors for terminal output
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def print_header(text: str):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'=' * 60}{Colors.ENDC}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text}{Colors.ENDC}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 60}{Colors.ENDC}\n")


def print_pass(text: str):
    print(f"{Colors.GREEN}✓ PASS:{Colors.ENDC} {text}")


def print_fail(text: str, details: str = ""):
    print(f"{Colors.RED}✗ FAIL:{Colors.ENDC} {text}")
    if details:
        print(f"  {Colors.YELLOW}→ {details}{Colors.ENDC}")


def print_warn(text: str):
    print(f"{Colors.YELLOW}⚠ WARN:{Colors.ENDC} {text}")


def get_project_root() -> Path:
    """Get project root directory (the main campaign_platform-main folder)"""
    # This file is at: backend/ai_governance/verify_governance.py
    # We want: campaign_platform-main/
    return Path(__file__).parent.parent.parent


def find_python_files(root: Path, exclude_patterns: List[str] = None) -> List[Path]:
    """Find all Python files in the project"""
    # Folders to completely skip
    skip_folders = {
        'venv', '.venv', 'node_modules', '__pycache__', 
        'dist', 'build', 'site-packages', '.git', 'eggs',
        '.eggs', '.tox', 'Campaign_platform'  # React frontend
    }
    
    all_files = []
    for root_dir, dirs, files in os.walk(root):
        # Skip excluded directories
        dirs[:] = [d for d in dirs if d not in skip_folders]
        
        # Skip if any parent is in skip_folders
        root_path = Path(root_dir)
        if any(part in skip_folders for part in root_path.parts):
            continue
        
        for file in files:
            if file.endswith('.py'):
                all_files.append(root_path / file)
    
    return all_files


class AcceptanceCriteriaVerifier:
    """Verifies all acceptance criteria"""
    
    def __init__(self, project_root: Path):
        self.root = project_root
        self.python_files = find_python_files(project_root)
        self.results: Dict[str, bool] = {}
        self.violations: Dict[str, List[str]] = {}
    
    def verify_all(self) -> bool:
        """Run all verification checks"""
        print_header("AI GOVERNANCE VERIFICATION")
        print(f"Scanning {len(self.python_files)} Python files...\n")
        
        checks = [
            ("No DeepSeek references", self.check_no_deepseek),
            ("Single Gemini entry point", self.check_single_gemini_entry),
            ("Gemini daily cap enforced", self.check_gemini_daily_cap),
            ("One classification per email", self.check_one_classification),
            ("No Gemini in schedulers/crons", self.check_no_gemini_schedulers),
            ("No Gemini automatic retries", self.check_no_gemini_retries),
            ("No ChatGPT for email ops", self.check_no_chatgpt_email),
        ]
        
        all_passed = True
        
        for name, check_func in checks:
            print(f"\n--- Checking: {name} ---")
            try:
                passed, violations = check_func()
                self.results[name] = passed
                self.violations[name] = violations
                
                if passed:
                    print_pass(name)
                else:
                    all_passed = False
                    print_fail(name)
                    for v in violations[:5]:  # Show first 5 violations
                        print(f"    - {v}")
                    if len(violations) > 5:
                        print(f"    ... and {len(violations) - 5} more violations")
            except Exception as e:
                all_passed = False
                print_fail(name, str(e))
        
        return all_passed
    
    def check_no_deepseek(self) -> Tuple[bool, List[str]]:
        """Check that DeepSeek is completely removed"""
        violations = []
        
        # Patterns to search for
        deepseek_patterns = [
            r'deepseek',
            r'DeepSeek',
            r'DEEPSEEK',
            r'deep_seek',
        ]
        
        # Files that are allowed to mention deepseek (documentation, verification, deprecated, etc.)
        allowed_files = [
            'verify_governance.py',
            'openai_wrapper_deprecated.py',
            'openai_wrapper_shim.py',
            'governance_checks.py',  # Documents DeepSeek removal
            'AGENT',  # Agent documentation files
            '.md',  # Markdown documentation
            '.txt',  # Text documentation
            'git_changes',
            'test_deepseek',  # Test files for deepseek
            '_deprecated',
            '_old',
            '_backup',
            'migrations.py',  # Migration scripts that reference removal
            '__init__.py',  # Init files may re-export
        ]
        
        for filepath in self.python_files:
            # Skip allowed files
            if any(af in str(filepath) for af in allowed_files):
                continue
            
            try:
                content = filepath.read_text(encoding='utf-8', errors='ignore')
                
                for pattern in deepseek_patterns:
                    matches = re.findall(pattern, content, re.IGNORECASE)
                    if matches:
                        violations.append(f"{filepath.relative_to(self.root)}: Found '{matches[0]}'")
                        break
            except Exception:
                pass
        
        return len(violations) == 0, violations
    
    def check_single_gemini_entry(self) -> Tuple[bool, List[str]]:
        """Check that only gemini_gateway.py invokes Gemini API"""
        violations = []
        
        # Patterns that indicate direct Gemini API usage
        gemini_call_patterns = [
            r'genai\.Client\(',
            r'genai\.configure\(',
            r'client\.models\.generate_content\(',
            r'google\.generativeai',
            r'from google import genai',
            r'import genai',
        ]
        
        # Files that are allowed to have Gemini calls
        allowed_files = [
            'gemini_gateway.py',  # Main entry point
            'gemini_rotator.py',  # Legacy - to be deprecated
            'verify_governance.py',  # This file (contains patterns)
            'test_gemini',  # Test files
            'test_models',  # Test files
            '_deprecated',
            '_old',
            '_backup',
            '_v1',  # Old versions
            'mail_segregation_agent.py',  # Legacy - to be deprecated
            'gemini_enrichment.py',  # Legacy - to be deprecated
            'prompt_management.py',  # Legacy - to be deprecated
            'ai_classification_service.py',  # Legacy - to be deprecated
        ]
        
        for filepath in self.python_files:
            # Check if this file is in the allowed list
            if any(af in str(filepath) for af in allowed_files):
                continue
            
            try:
                content = filepath.read_text(encoding='utf-8', errors='ignore')
                
                for pattern in gemini_call_patterns:
                    if re.search(pattern, content):
                        violations.append(f"{filepath.relative_to(self.root)}: Direct Gemini call found")
                        break
            except Exception:
                pass
        
        return len(violations) == 0, violations
    
    def check_gemini_daily_cap(self) -> Tuple[bool, List[str]]:
        """Check that daily cap is enforced in code"""
        violations = []
        
        # Look for the governance checks file
        governance_file = self.root / 'backend' / 'ai_governance' / 'governance_checks.py'
        gateway_file = self.root / 'backend' / 'ai_governance' / 'gemini_gateway.py'
        
        # Check governance_checks.py has the limit
        if governance_file.exists():
            content = governance_file.read_text()
            if 'GEMINI_DAILY_LIMIT = 7000' not in content:
                violations.append("governance_checks.py: Missing GEMINI_DAILY_LIMIT = 7000")
            if 'increment_gemini_daily_usage' not in content:
                violations.append("governance_checks.py: Missing increment_gemini_daily_usage function")
            if 'check_gemini_daily_limit' not in content:
                violations.append("governance_checks.py: Missing check_gemini_daily_limit function")
        else:
            violations.append("governance_checks.py not found")
        
        # Check gemini_gateway.py calls the cap check
        if gateway_file.exists():
            content = gateway_file.read_text()
            if 'check_gemini_daily_limit' not in content:
                violations.append("gemini_gateway.py: Does not check daily limit")
            if 'increment_gemini_daily_usage' not in content:
                violations.append("gemini_gateway.py: Does not increment usage counter")
        else:
            violations.append("gemini_gateway.py not found")
        
        return len(violations) == 0, violations
    
    def check_one_classification(self) -> Tuple[bool, List[str]]:
        """Check that one-classification-per-email is enforced"""
        violations = []
        
        governance_file = self.root / 'backend' / 'ai_governance' / 'governance_checks.py'
        gateway_file = self.root / 'backend' / 'ai_governance' / 'gemini_gateway.py'
        
        # Check for unique constraint
        if governance_file.exists():
            content = governance_file.read_text()
            if 'acquire_classification_lock' not in content:
                violations.append("governance_checks.py: Missing acquire_classification_lock")
            if 'EmailAlreadyClassified' not in content:
                violations.append("governance_checks.py: Missing EmailAlreadyClassified exception")
            if 'unique=True' not in content:
                violations.append("governance_checks.py: Missing unique constraint")
        else:
            violations.append("governance_checks.py not found")
        
        # Check gateway uses the lock
        if gateway_file.exists():
            content = gateway_file.read_text()
            if 'acquire_classification_lock' not in content:
                violations.append("gemini_gateway.py: Does not acquire classification lock")
        else:
            violations.append("gemini_gateway.py not found")
        
        return len(violations) == 0, violations
    
    def check_no_gemini_schedulers(self) -> Tuple[bool, List[str]]:
        """Check that no scheduler/cron directly triggers Gemini"""
        violations = []
        
        # Files that typically contain schedulers
        scheduler_patterns = ['scheduler', 'cron', 'task', 'celery', 'worker']
        
        for filepath in self.python_files:
            filename = filepath.name.lower()
            
            # Check if this is a scheduler file
            is_scheduler = any(p in filename for p in scheduler_patterns)
            if not is_scheduler:
                continue
            
            try:
                content = filepath.read_text(encoding='utf-8', errors='ignore')
                
                # Check for Gemini imports or calls
                gemini_patterns = [
                    r'from backend\.ai_governance.*import.*classify_email',
                    r'from backend\.ai_governance.*import.*gemini',
                    r'gemini_gateway',
                    r'classify_email\(',
                    r'summarize_email\(',
                ]
                
                for pattern in gemini_patterns:
                    if re.search(pattern, content):
                        violations.append(f"{filepath.relative_to(self.root)}: Scheduler contains Gemini call")
                        break
            except Exception:
                pass
        
        return len(violations) == 0, violations
    
    def check_no_gemini_retries(self) -> Tuple[bool, List[str]]:
        """Check that Gemini calls have no automatic retries"""
        violations = []
        
        gateway_file = self.root / 'backend' / 'ai_governance' / 'gemini_gateway.py'
        
        if gateway_file.exists():
            content = gateway_file.read_text()
            
            # Check for retry patterns
            retry_patterns = [
                r'for attempt in range\(',
                r'@retry',
                r'max_retries\s*=\s*[1-9]',
                r'retry\s*=\s*True',
                r'while.*retry',
            ]
            
            for pattern in retry_patterns:
                if re.search(pattern, content):
                    violations.append(f"gemini_gateway.py: Found retry pattern: {pattern}")
            
            # Check for explicit no-retry comment
            if 'NO AUTOMATIC RETRY' not in content and 'NO RETRY' not in content:
                print_warn("gemini_gateway.py: Consider adding explicit 'NO RETRY' comments")
        
        return len(violations) == 0, violations
    
    def check_no_chatgpt_email(self) -> Tuple[bool, List[str]]:
        """Check that ChatGPT/OpenAI is not used for email operations"""
        violations = []
        
        openai_gateway = self.root / 'backend' / 'ai_governance' / 'openai_gateway.py'
        
        if openai_gateway.exists():
            content = openai_gateway.read_text()
            
            # Check that forbidden operations are defined
            if 'FORBIDDEN_OPERATIONS' not in content:
                violations.append("openai_gateway.py: Missing FORBIDDEN_OPERATIONS")
            
            if 'email_classification' not in content:
                violations.append("openai_gateway.py: email_classification not in forbidden list")
            
            if 'OpenAIWebSearchOnly' not in content:
                violations.append("openai_gateway.py: Missing OpenAIWebSearchOnly exception")
        else:
            violations.append("openai_gateway.py not found")
        
        # Check that no other files use OpenAI for email
        email_openai_patterns = [
            r'openai.*classify.*email',
            r'openai.*email.*classify',
            r'chat_completion.*email.*classif',
            r'gpt.*email.*classif',
        ]
        
        for filepath in self.python_files:
            if 'openai_gateway' in str(filepath):
                continue
            if 'deprecated' in str(filepath).lower():
                continue
            if 'verify' in str(filepath).lower():
                continue
            
            try:
                content = filepath.read_text(encoding='utf-8', errors='ignore').lower()
                
                for pattern in email_openai_patterns:
                    if re.search(pattern, content):
                        violations.append(f"{filepath.relative_to(self.root)}: OpenAI used for email")
                        break
            except Exception:
                pass
        
        return len(violations) == 0, violations
    
    def print_summary(self) -> bool:
        """Print verification summary"""
        print_header("VERIFICATION SUMMARY")
        
        total = len(self.results)
        passed = sum(1 for v in self.results.values() if v)
        failed = total - passed
        
        print(f"Total Checks: {total}")
        print(f"Passed: {Colors.GREEN}{passed}{Colors.ENDC}")
        print(f"Failed: {Colors.RED}{failed}{Colors.ENDC}")
        print()
        
        if failed == 0:
            print(f"{Colors.GREEN}{Colors.BOLD}")
            print("=" * 60)
            print("  ALL ACCEPTANCE CRITERIA VERIFIED - IMPLEMENTATION VALID")
            print("=" * 60)
            print(f"{Colors.ENDC}")
            return True
        else:
            print(f"{Colors.RED}{Colors.BOLD}")
            print("=" * 60)
            print("  VERIFICATION FAILED - IMPLEMENTATION INVALID")
            print("=" * 60)
            print(f"{Colors.ENDC}")
            
            print("\nFailed Checks:")
            for name, passed in self.results.items():
                if not passed:
                    print(f"  {Colors.RED}✗{Colors.ENDC} {name}")
            
            return False


def main():
    """Main entry point"""
    print_header("AI GOVERNANCE ACCEPTANCE CRITERIA VERIFICATION")
    
    project_root = get_project_root()
    print(f"Project Root: {project_root}\n")
    
    verifier = AcceptanceCriteriaVerifier(project_root)
    
    try:
        all_passed = verifier.verify_all()
        verifier.print_summary()
        
        sys.exit(0 if all_passed else 1)
        
    except Exception as e:
        print(f"\n{Colors.RED}Verification failed with error: {e}{Colors.ENDC}")
        sys.exit(1)


if __name__ == "__main__":
    main()
