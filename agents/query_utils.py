# agents/query_utils.py

def clean_query_output(raw_query: str, service: str, industry: str, location: str, site: str) -> str:
    """
    Cleans the raw output from an LLM to produce a valid Google search query.
    If the query is empty or lacks context, it builds a robust fallback query.
    """
    if not raw_query:
        return f'"{industry}" "{service}" "{location}" site:{site}'
    
    # Take the last line in case of multi-line output
    cleaned = raw_query.strip().split("\n")[-1].strip()
    
    # Heuristic check: if the query is very short or misses key terms, rebuild it
    if len(cleaned) < 15 or not all(k.lower() in cleaned.lower() for k in [service, industry, location]):
        cleaned = f'"{industry}" "{service}" "{location}"'

    # Ensure the site constraint is present
    if site and f"site:{site}" not in cleaned:
        cleaned += f" site:{site}"
        
    return cleaned
