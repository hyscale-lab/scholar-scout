import os
import json
import argparse
from collections import Counter
from itertools import combinations
from datetime import datetime

def calculate_stats(papers):
    """Calculates basic statistics and co-occurrences for a given set of papers."""
    stats = {
        "total": len(papers),
        "categories": Counter(),
        "co_occurrences": Counter()
    }
    
    if not papers:
        return stats
        
    for p in papers:
        raw_cats = p.get("category") or p.get("categories") or p.get("predicted_categories") or p.get("labels", [])
        cats = []
        if isinstance(raw_cats, list):
            cats = [c for c in raw_cats if isinstance(c, str) and c != "Others"]
        elif isinstance(raw_cats, str) and raw_cats != "Others":
            cats = [raw_cats]
            
        for cat in cats:
            stats["categories"][cat] += 1
            
        if len(cats) > 1:
            for pair in combinations(sorted(cats), 2):
                stats["co_occurrences"][f"{pair[0]} + {pair[1]}"] += 1
                
    return stats

def get_growth_narrative(category, curr_val, prev_val):
    """Applies deterministic rules to generate narrative sentences for growth."""
    if prev_val == 0 and curr_val > 0:
        return f"• *{category}* is a newly appeared category this month ({curr_val} papers)."
    if curr_val == 0 and prev_val > 0:
        return f"• *{category}* disappeared completely this month."
    if prev_val == 0 and curr_val == 0:
        return None
        
    delta = curr_val - prev_val
    growth_pct = (delta / prev_val) * 100
    
    if growth_pct > 30:
        verb = "experienced strong growth"
    elif growth_pct > 10:
        verb = "showed moderate growth"
    elif growth_pct > -10:
        verb = "remained relatively stable"
    elif growth_pct > -30:
        verb = "declined"
    else:
        verb = "experienced a sharp decline"
        
    sign = "+" if delta > 0 else ""
    return f"• *{category}* {verb}, changing by {delta} papers ({sign}{growth_pct:.0f}% vs previous period)."

def generate_trend_report(current_month_name, curr_stats, prev_stats):
    """Orchestrates the analytics pipeline and returns Slack markdown."""
    if curr_stats["total"] == 0:
        return "No new papers were classified this period."
        
    report_lines = [
        "*Scholar Scout: Monthly Trend Report*",
        f"_Reporting Period: {current_month_name}_",
        "",
        f"Processed *{curr_stats['total']}* newly classified papers.",
        "",
        "*Key Observations*"
    ]
    
    # 1. Dominant Topic
    if curr_stats["categories"]:
        dominant_cat, dom_count = curr_stats["categories"].most_common(1)[0]
        dom_pct = (dom_count / curr_stats["total"]) * 100
        prev_dom_count = prev_stats["categories"].get(dominant_cat, 0)
        dom_delta_str = ""
        if prev_dom_count > 0:
            dom_delta = dom_count - prev_dom_count
            dom_growth = (dom_delta / prev_dom_count) * 100
            sign = "+" if dom_delta > 0 else ""
            dom_delta_str = f" ({sign}{dom_growth:.0f}% vs previous period)"
            
        report_lines.append(
            f"• *{dominant_cat}* was the dominant topic, accounting for {dom_pct:.0f}% of all classified papers{dom_delta_str}."
        )

    # 2. Category Growth Narratives
    all_categories = set(curr_stats["categories"].keys()) | set(prev_stats["categories"].keys())
    if curr_stats["categories"]:
        all_categories.discard(curr_stats["categories"].most_common(1)[0][0])
        
    for cat in sorted(all_categories):
        narrative = get_growth_narrative(cat, curr_stats["categories"].get(cat, 0), prev_stats["categories"].get(cat, 0))
        if narrative:
            report_lines.append(narrative)
            
    # 3. Relationship Mining
    if curr_stats["co_occurrences"]:
        top_pair, top_pair_count = curr_stats["co_occurrences"].most_common(1)[0]
        prev_pair_count = prev_stats["co_occurrences"].get(top_pair, 0)
        
        pair_delta_str = ""
        if prev_pair_count > 0:
            pair_growth = ((top_pair_count - prev_pair_count) / prev_pair_count) * 100
            sign = "+" if top_pair_count > prev_pair_count else ""
            pair_delta_str = f" ({sign}{pair_growth:.0f}% vs previous period)"
            
        report_lines.append(
            f"• The most common topic combination was *{top_pair}* ({top_pair_count} papers){pair_delta_str}."
        )
        
    return "\n".join(report_lines)

def run_analytics_engine(current_period=None, previous_period=None):
    """
    Reads the JSON ledger, buckets by date, and generates the report.
    
    If periods are not provided, it defaults to the current month vs previous month.
    Periods should be in 'YYYY-MM' format.
    """
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    db_path = os.path.join(project_root, "data", "classified_papers.json")
    
    if not os.path.exists(db_path):
        return None

    with open(db_path, "r", encoding="utf-8") as f:
        all_papers = json.load(f)

    # Automatic Date Derivation if arguments are None
    if current_period is None or previous_period is None:
        today = datetime.now()
        current_period = today.strftime("%Y-%m")
        
        prev_month = today.month - 1
        prev_year = today.year
        if prev_month == 0:
            prev_month = 12
            prev_year -= 1
        previous_period = f"{prev_year}-{prev_month:02d}"
        
        # Display name for the report (e.g., "August 2026")
        display_name = today.strftime("%B %Y")
    else:
        display_name = current_period # Use the raw string if manually overridden

    current_bucket = []
    previous_bucket = []

    # Loop through every paper and bucket them
    for paper in all_papers:
        date_added = paper.get("date_added", "")
        if not date_added:
            continue
            
        # Extract just the "YYYY-MM" part from "YYYY-MM-DD"
        paper_month = date_added[:7]
        
        if paper_month == current_period:
            current_bucket.append(paper)
        elif paper_month == previous_period:
            previous_bucket.append(paper)

    curr_stats = calculate_stats(current_bucket)
    prev_stats = calculate_stats(previous_bucket)

    report_markdown = generate_trend_report(
        current_month_name=display_name, 
        curr_stats=curr_stats, 
        prev_stats=prev_stats
    )
    
    return report_markdown

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scholar Scout Trend Analyzer")
    parser.add_argument("--current", type=str, help="Current period (YYYY-MM)")
    parser.add_argument("--previous", type=str, help="Previous period (YYYY-MM)")
    args = parser.parse_args()
    
    # If both or neither are provided, run the engine
    if (args.current and not args.previous) or (args.previous and not args.current):
        print("Error: You must provide BOTH --current and --previous, or NEITHER.")
    else:
        report = run_analytics_engine(current_period=args.current, previous_period=args.previous)
        print(report)