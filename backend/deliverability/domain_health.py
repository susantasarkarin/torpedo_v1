"""
Domain Health Service - DNS-Based Email Deliverability Monitoring

Performs comprehensive DNS health checks including SPF, DKIM, DMARC,
and MX record validation. Calculates composite health scores.

Dependencies: dnspython
Installation: pip install dnspython

Author: Agent 6
Date: 2026-01-28
"""

import dns.resolver
import dns.exception
from typing import Dict, List, Optional, Tuple
import logging
import re

logger = logging.getLogger(__name__)


class DomainHealthService:
    """DNS-based domain health monitoring service."""
    
    # Common DKIM selectors to check
    COMMON_DKIM_SELECTORS = [
        'default',
        'google',
        'ses',
        'k1',
        'k2',
        's1',
        's2',
        'mail',
        'email',
        'smtp',
        'dkim',
        'selector1',
        'selector2'
    ]
    
    # Health score weights
    WEIGHT_SPF = 25
    WEIGHT_DKIM = 25
    WEIGHT_DMARC = 25
    WEIGHT_MX = 25
    
    def __init__(self, timeout: float = 5.0):
        """
        Initialize domain health service.
        
        Args:
            timeout: DNS query timeout in seconds
        """
        self.timeout = timeout
        self.resolver = dns.resolver.Resolver()
        self.resolver.lifetime = timeout
        logger.info("DomainHealthService initialized")
    
    def check_spf(self, domain: str) -> Dict:
        """
        Check SPF record for a domain.
        
        SPF (Sender Policy Framework) specifies which mail servers
        are authorized to send email on behalf of the domain.
        
        Args:
            domain: Domain name to check
            
        Returns:
            Dictionary with:
                - status: "pass", "fail", "none", or "error"
                - record: SPF record text or None
                - valid: Boolean indicating if record is valid
                - details: Additional information
        """
        try:
            logger.debug(f"Checking SPF for domain: {domain}")
            
            # Query TXT records
            answers = dns.resolver.resolve(domain, 'TXT', lifetime=self.timeout)
            
            spf_records = []
            for rdata in answers:
                # Join all strings in TXT record
                txt = ''.join([s.decode() if isinstance(s, bytes) else s for s in rdata.strings])
                
                # Check if it's an SPF record
                if txt.strip().startswith('v=spf1'):
                    spf_records.append(txt)
            
            if len(spf_records) == 0:
                return {
                    "status": "none",
                    "record": None,
                    "valid": False,
                    "details": "No SPF record found"
                }
            
            if len(spf_records) > 1:
                return {
                    "status": "fail",
                    "record": spf_records[0],
                    "valid": False,
                    "details": f"Multiple SPF records found ({len(spf_records)}). Only one is allowed."
                }
            
            spf_record = spf_records[0]
            
            # Validate SPF record
            is_valid, validation_msg = self._validate_spf_record(spf_record)
            
            return {
                "status": "pass" if is_valid else "fail",
                "record": spf_record,
                "valid": is_valid,
                "details": validation_msg
            }
            
        except dns.resolver.NXDOMAIN:
            return {
                "status": "error",
                "record": None,
                "valid": False,
                "details": "Domain does not exist"
            }
        except dns.resolver.NoAnswer:
            return {
                "status": "none",
                "record": None,
                "valid": False,
                "details": "No TXT records found"
            }
        except dns.exception.Timeout:
            return {
                "status": "error",
                "record": None,
                "valid": False,
                "details": "DNS query timeout"
            }
        except Exception as e:
            logger.error(f"Error checking SPF for {domain}: {e}")
            return {
                "status": "error",
                "record": None,
                "valid": False,
                "details": str(e)
            }
    
    def _validate_spf_record(self, record: str) -> Tuple[bool, str]:
        """Validate SPF record syntax and content."""
        try:
            # Check for required elements
            if not record.startswith('v=spf1'):
                return False, "SPF record must start with 'v=spf1'"
            
            # Check for terminator (all mechanism)
            if not any(term in record for term in ['-all', '~all', '?all', '+all']):
                return False, "SPF record should have an 'all' terminator"
            
            # Warn about too permissive policies
            if '+all' in record:
                return True, "Warning: SPF policy is too permissive (+all)"
            
            # Count DNS lookups (should be <= 10)
            lookup_mechanisms = ['include:', 'a:', 'mx:', 'ptr:', 'exists:']
            lookup_count = sum(record.count(mech) for mech in lookup_mechanisms)
            
            if lookup_count > 10:
                return False, f"SPF record exceeds 10 DNS lookup limit ({lookup_count} lookups)"
            
            return True, "SPF record is valid"
            
        except Exception as e:
            return False, f"SPF validation error: {e}"
    
    def check_dkim(self, domain: str, selector: str = "default") -> Dict:
        """
        Check DKIM record for a domain.
        
        DKIM (DomainKeys Identified Mail) allows the receiver to verify
        that an email was indeed sent by the owner of that domain.
        
        Args:
            domain: Domain name to check
            selector: DKIM selector (default: "default")
            
        Returns:
            Dictionary with:
                - status: "pass", "fail", "none", or "error"
                - selector: Selector used
                - record: DKIM record text or None
                - valid: Boolean indicating if record is valid
                - details: Additional information
        """
        try:
            logger.debug(f"Checking DKIM for domain: {domain}, selector: {selector}")
            
            # Construct DKIM query: selector._domainkey.domain
            dkim_domain = f"{selector}._domainkey.{domain}"
            
            # Query TXT records
            answers = dns.resolver.resolve(dkim_domain, 'TXT', lifetime=self.timeout)
            
            dkim_records = []
            for rdata in answers:
                txt = ''.join([s.decode() if isinstance(s, bytes) else s for s in rdata.strings])
                
                # Check if it's a DKIM record
                if 'v=DKIM1' in txt or 'p=' in txt:
                    dkim_records.append(txt)
            
            if len(dkim_records) == 0:
                return {
                    "status": "none",
                    "selector": selector,
                    "record": None,
                    "valid": False,
                    "details": f"No DKIM record found for selector '{selector}'"
                }
            
            dkim_record = dkim_records[0]
            
            # Validate DKIM record
            is_valid, validation_msg = self._validate_dkim_record(dkim_record)
            
            return {
                "status": "pass" if is_valid else "fail",
                "selector": selector,
                "record": dkim_record,
                "valid": is_valid,
                "details": validation_msg
            }
            
        except dns.resolver.NXDOMAIN:
            return {
                "status": "none",
                "selector": selector,
                "record": None,
                "valid": False,
                "details": f"No DKIM record found for selector '{selector}'"
            }
        except dns.resolver.NoAnswer:
            return {
                "status": "none",
                "selector": selector,
                "record": None,
                "valid": False,
                "details": "No TXT records found"
            }
        except dns.exception.Timeout:
            return {
                "status": "error",
                "selector": selector,
                "record": None,
                "valid": False,
                "details": "DNS query timeout"
            }
        except Exception as e:
            logger.error(f"Error checking DKIM for {domain}: {e}")
            return {
                "status": "error",
                "selector": selector,
                "record": None,
                "valid": False,
                "details": str(e)
            }
    
    def _validate_dkim_record(self, record: str) -> Tuple[bool, str]:
        """Validate DKIM record syntax and content."""
        try:
            # Check for public key
            if 'p=' not in record:
                return False, "DKIM record missing public key (p=)"
            
            # Extract public key
            p_match = re.search(r'p=([A-Za-z0-9+/=]+)', record)
            if p_match:
                public_key = p_match.group(1)
                if len(public_key) < 50:
                    return False, "DKIM public key appears too short"
            
            # Check for revoked key
            if 'p=' in record and record.split('p=')[1].strip().startswith(';'):
                return False, "DKIM key has been revoked"
            
            return True, "DKIM record is valid"
            
        except Exception as e:
            return False, f"DKIM validation error: {e}"
    
    def check_dkim_auto(self, domain: str) -> Dict:
        """
        Automatically check multiple common DKIM selectors.
        
        Args:
            domain: Domain name to check
            
        Returns:
            Dictionary with results for all selectors checked
        """
        results = {
            "domain": domain,
            "selectors_checked": [],
            "valid_selectors": [],
            "best_result": None
        }
        
        for selector in self.COMMON_DKIM_SELECTORS:
            result = self.check_dkim(domain, selector)
            results["selectors_checked"].append(selector)
            
            if result["status"] == "pass":
                results["valid_selectors"].append(selector)
                if results["best_result"] is None:
                    results["best_result"] = result
        
        return results
    
    def check_dmarc(self, domain: str) -> Dict:
        """
        Check DMARC record for a domain.
        
        DMARC (Domain-based Message Authentication, Reporting & Conformance)
        builds on SPF and DKIM to protect against email spoofing.
        
        Args:
            domain: Domain name to check
            
        Returns:
            Dictionary with:
                - status: "pass", "fail", "none", or "error"
                - record: DMARC record text or None
                - policy: DMARC policy (none, quarantine, reject)
                - valid: Boolean indicating if record is valid
                - details: Additional information
        """
        try:
            logger.debug(f"Checking DMARC for domain: {domain}")
            
            # Construct DMARC query: _dmarc.domain
            dmarc_domain = f"_dmarc.{domain}"
            
            # Query TXT records
            answers = dns.resolver.resolve(dmarc_domain, 'TXT', lifetime=self.timeout)
            
            dmarc_records = []
            for rdata in answers:
                txt = ''.join([s.decode() if isinstance(s, bytes) else s for s in rdata.strings])
                
                # Check if it's a DMARC record
                if txt.strip().startswith('v=DMARC1'):
                    dmarc_records.append(txt)
            
            if len(dmarc_records) == 0:
                return {
                    "status": "none",
                    "record": None,
                    "policy": None,
                    "valid": False,
                    "details": "No DMARC record found"
                }
            
            if len(dmarc_records) > 1:
                return {
                    "status": "fail",
                    "record": dmarc_records[0],
                    "policy": None,
                    "valid": False,
                    "details": f"Multiple DMARC records found ({len(dmarc_records)})"
                }
            
            dmarc_record = dmarc_records[0]
            
            # Extract policy
            policy = self._extract_dmarc_policy(dmarc_record)
            
            # Validate DMARC record
            is_valid, validation_msg = self._validate_dmarc_record(dmarc_record)
            
            return {
                "status": "pass" if is_valid else "fail",
                "record": dmarc_record,
                "policy": policy,
                "valid": is_valid,
                "details": validation_msg
            }
            
        except dns.resolver.NXDOMAIN:
            return {
                "status": "none",
                "record": None,
                "policy": None,
                "valid": False,
                "details": "No DMARC record found"
            }
        except dns.resolver.NoAnswer:
            return {
                "status": "none",
                "record": None,
                "policy": None,
                "valid": False,
                "details": "No TXT records found"
            }
        except dns.exception.Timeout:
            return {
                "status": "error",
                "record": None,
                "policy": None,
                "valid": False,
                "details": "DNS query timeout"
            }
        except Exception as e:
            logger.error(f"Error checking DMARC for {domain}: {e}")
            return {
                "status": "error",
                "record": None,
                "policy": None,
                "valid": False,
                "details": str(e)
            }
    
    def _extract_dmarc_policy(self, record: str) -> Optional[str]:
        """Extract DMARC policy from record."""
        match = re.search(r'p=(none|quarantine|reject)', record)
        if match:
            return match.group(1)
        return None
    
    def _validate_dmarc_record(self, record: str) -> Tuple[bool, str]:
        """Validate DMARC record syntax and content."""
        try:
            if not record.startswith('v=DMARC1'):
                return False, "DMARC record must start with 'v=DMARC1'"
            
            # Check for policy
            policy = self._extract_dmarc_policy(record)
            if not policy:
                return False, "DMARC record missing policy (p=)"
            
            # Provide policy feedback
            if policy == 'none':
                return True, "DMARC policy is 'none' (monitoring only)"
            elif policy == 'quarantine':
                return True, "DMARC policy is 'quarantine' (good)"
            elif policy == 'reject':
                return True, "DMARC policy is 'reject' (excellent)"
            
            return True, "DMARC record is valid"
            
        except Exception as e:
            return False, f"DMARC validation error: {e}"
    
    def check_mx_records(self, domain: str) -> List[str]:
        """
        Check MX records for a domain.
        
        MX (Mail Exchange) records specify the mail servers responsible
        for accepting email on behalf of the domain.
        
        Args:
            domain: Domain name to check
            
        Returns:
            List of MX record hostnames (sorted by priority)
        """
        try:
            logger.debug(f"Checking MX records for domain: {domain}")
            
            answers = dns.resolver.resolve(domain, 'MX', lifetime=self.timeout)
            
            # Sort by priority (lower is higher priority)
            mx_records = sorted(
                [(r.preference, str(r.exchange).rstrip('.')) for r in answers],
                key=lambda x: x[0]
            )
            
            # Return just the hostnames
            return [mx[1] for mx in mx_records]
            
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.exception.Timeout):
            logger.warning(f"No MX records found for {domain}")
            return []
        except Exception as e:
            logger.error(f"Error checking MX records for {domain}: {e}")
            return []
    
    def calculate_health_score(self, domain: str) -> Dict:
        """
        Calculate comprehensive domain health score.
        
        Scoring breakdown:
        - SPF: 25 points (pass=25, none=0, fail=0)
        - DKIM: 25 points (pass=25, none=0, fail=0)
        - DMARC: 25 points (reject=25, quarantine=20, none=10, missing=0)
        - MX: 25 points (has records=25, none=0)
        
        Args:
            domain: Domain name to check
            
        Returns:
            Dictionary with:
                - score: Overall health score (0-100)
                - spf: SPF check result
                - dkim: DKIM check result
                - dmarc: DMARC check result
                - mx: MX records
                - breakdown: Point breakdown by category
                - grade: Letter grade (A, B, C, D, F)
        """
        logger.info(f"Calculating health score for domain: {domain}")
        
        score = 0
        breakdown = {}
        
        # Check SPF
        spf_result = self.check_spf(domain)
        if spf_result["status"] == "pass":
            spf_points = self.WEIGHT_SPF
        else:
            spf_points = 0
        score += spf_points
        breakdown["spf"] = spf_points
        
        # Check DKIM (try auto-detection)
        dkim_result = self.check_dkim_auto(domain)
        if len(dkim_result["valid_selectors"]) > 0:
            dkim_points = self.WEIGHT_DKIM
        else:
            dkim_points = 0
        score += dkim_points
        breakdown["dkim"] = dkim_points
        
        # Check DMARC
        dmarc_result = self.check_dmarc(domain)
        if dmarc_result["status"] == "pass":
            policy = dmarc_result.get("policy")
            if policy == "reject":
                dmarc_points = self.WEIGHT_DMARC
            elif policy == "quarantine":
                dmarc_points = int(self.WEIGHT_DMARC * 0.8)
            elif policy == "none":
                dmarc_points = int(self.WEIGHT_DMARC * 0.4)
            else:
                dmarc_points = 0
        else:
            dmarc_points = 0
        score += dmarc_points
        breakdown["dmarc"] = dmarc_points
        
        # Check MX records
        mx_records = self.check_mx_records(domain)
        if len(mx_records) > 0:
            mx_points = self.WEIGHT_MX
        else:
            mx_points = 0
        score += mx_points
        breakdown["mx"] = mx_points
        
        # Determine grade
        if score >= 90:
            grade = "A"
        elif score >= 80:
            grade = "B"
        elif score >= 70:
            grade = "C"
        elif score >= 60:
            grade = "D"
        else:
            grade = "F"
        
        result = {
            "domain": domain,
            "score": score,
            "grade": grade,
            "breakdown": breakdown,
            "spf": spf_result,
            "dkim": dkim_result,
            "dmarc": dmarc_result,
            "mx": mx_records,
            "timestamp": dns.resolver.datetime.datetime.utcnow().isoformat()
        }
        
        logger.info(f"Health score for {domain}: {score}/100 (Grade: {grade})")
        return result
    
    def get_recommendations(self, health_result: Dict) -> List[str]:
        """
        Generate recommendations based on health check results.
        
        Args:
            health_result: Result from calculate_health_score()
            
        Returns:
            List of recommendation strings
        """
        recommendations = []
        
        # SPF recommendations
        spf = health_result.get("spf", {})
        if spf.get("status") == "none":
            recommendations.append("Add an SPF record to authorize mail servers")
        elif spf.get("status") == "fail":
            recommendations.append(f"Fix SPF record: {spf.get('details')}")
        
        # DKIM recommendations
        dkim = health_result.get("dkim", {})
        if len(dkim.get("valid_selectors", [])) == 0:
            recommendations.append("Configure DKIM signing for your domain")
        
        # DMARC recommendations
        dmarc = health_result.get("dmarc", {})
        if dmarc.get("status") == "none":
            recommendations.append("Add a DMARC record to protect against spoofing")
        elif dmarc.get("policy") == "none":
            recommendations.append("Upgrade DMARC policy from 'none' to 'quarantine' or 'reject'")
        elif dmarc.get("policy") == "quarantine":
            recommendations.append("Consider upgrading DMARC policy to 'reject' for maximum protection")
        
        # MX recommendations
        mx = health_result.get("mx", [])
        if len(mx) == 0:
            recommendations.append("Add MX records to enable email delivery")
        
        if len(recommendations) == 0:
            recommendations.append("Domain health is excellent! No improvements needed.")
        
        return recommendations


# Convenience functions for direct use
def check_spf(domain: str) -> Dict:
    """Convenience function to check SPF."""
    service = DomainHealthService()
    return service.check_spf(domain)


def check_dkim(domain: str, selector: str = "default") -> Dict:
    """Convenience function to check DKIM."""
    service = DomainHealthService()
    return service.check_dkim(domain, selector)


def check_dmarc(domain: str) -> Dict:
    """Convenience function to check DMARC."""
    service = DomainHealthService()
    return service.check_dmarc(domain)


def check_mx_records(domain: str) -> List[str]:
    """Convenience function to check MX records."""
    service = DomainHealthService()
    return service.check_mx_records(domain)


def calculate_health_score(domain: str) -> Dict:
    """Convenience function to calculate health score."""
    service = DomainHealthService()
    return service.calculate_health_score(domain)


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Test with a well-known domain
    test_domain = "google.com"
    
    service = DomainHealthService()
    
    print(f"\n{'='*60}")
    print(f"Domain Health Check: {test_domain}")
    print(f"{'='*60}\n")
    
    # Full health check
    result = service.calculate_health_score(test_domain)
    
    print(f"Overall Score: {result['score']}/100 (Grade: {result['grade']})")
    print(f"\nBreakdown:")
    print(f"  - SPF:   {result['breakdown']['spf']}/{service.WEIGHT_SPF} points")
    print(f"  - DKIM:  {result['breakdown']['dkim']}/{service.WEIGHT_DKIM} points")
    print(f"  - DMARC: {result['breakdown']['dmarc']}/{service.WEIGHT_DMARC} points")
    print(f"  - MX:    {result['breakdown']['mx']}/{service.WEIGHT_MX} points")
    
    print(f"\nRecommendations:")
    for i, rec in enumerate(service.get_recommendations(result), 1):
        print(f"  {i}. {rec}")
    
    print(f"\n{'='*60}\n")
