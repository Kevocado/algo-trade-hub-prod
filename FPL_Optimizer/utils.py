import re

def extract_team_id_from_url(url_or_id: str) -> str:
    """Extract team ID from FPL URL or return if already an ID"""
    if not url_or_id:
        return None
        
    if str(url_or_id).isdigit():
        return str(url_or_id)
    
    patterns = [
        r'fantasy\.premierleague\.com/entry/(\d+)',
        r'/entry/(\d+)/',
        r'/entry/(\d+)',
        r'team/(\d+)',
        r'(\d+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, str(url_or_id))
        if match:
            return match.group(1)
    
    numbers = re.findall(r'\d+', str(url_or_id))
    if numbers:
        return max(numbers, key=len)
    
    return None
