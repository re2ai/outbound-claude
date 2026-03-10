#!/usr/bin/env python3
"""Pull SmartLead campaign stats for Resquared scorecard."""
import os
import sys
import json
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from collections import defaultdict

load_dotenv()

API_KEY = os.getenv("SMARTLEAD_API_KEY")
BASE_URL = "https://server.smartlead.ai/api/v1"

def api_get(endpoint, params=None):
    """Make GET request to SmartLead API."""
    if params is None:
        params = {}
    params['api_key'] = API_KEY
    url = f"{BASE_URL}/{endpoint}"
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()

def get_all_campaigns():
    """Get all campaigns."""
    return api_get("campaigns/")

def get_campaign_analytics(campaign_id):
    """Get top-level analytics for a campaign."""
    return api_get(f"campaigns/{campaign_id}/analytics")

def get_campaign_statistics(campaign_id, start_date=None, end_date=None):
    """Get per-email statistics for a campaign with optional date filtering."""
    params = {}
    if start_date:
        params['sent_time_start_date'] = f"{start_date}T00:00:00.000Z"
    if end_date:
        # end_date should be exclusive, so add 1 day
        params['sent_time_end_date'] = f"{end_date}T23:59:59.999Z"

    all_data = []
    offset = 0
    while True:
        params['offset'] = offset
        result = api_get(f"campaigns/{campaign_id}/statistics", params)
        data = result.get('data', []) if isinstance(result, dict) else result
        if not data:
            break
        all_data.extend(data)
        if len(data) < 500:  # Less than page size means last page
            break
        offset += len(data)
        if offset > 50000:  # Safety limit
            break

    return all_data

def is_plg_campaign(campaign_name):
    """Check if campaign is a PLG (internal marketing) campaign."""
    return 'PLG' in campaign_name.upper()

def get_week_bounds(ref_date=None):
    """Get Sunday-Saturday bounds. If ref_date is None, use last complete week."""
    if ref_date is None:
        ref_date = datetime.now().date()
    # Find last Saturday
    days_since_saturday = (ref_date.weekday() + 2) % 7
    if days_since_saturday == 0:
        days_since_saturday = 7  # Go to previous Saturday
    saturday = ref_date - timedelta(days=days_since_saturday)
    sunday = saturday - timedelta(days=6)
    return sunday, saturday

def filter_stats_by_date(stats_data, start_date, end_date):
    """Filter statistics to a date range based on sent_time (backup if API filtering fails)."""
    filtered = []
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)

    for stat in stats_data:
        sent_time = stat.get('sent_time')
        if sent_time:
            try:
                sent_dt = datetime.fromisoformat(sent_time.replace('Z', '+00:00')).replace(tzinfo=None)
                if start_dt <= sent_dt < end_dt:
                    filtered.append(stat)
            except:
                pass
    return filtered if filtered else stats_data  # Return all if filtering fails

def aggregate_stats(stats_list):
    """Aggregate stats from a list of per-email records."""
    # Positive categories = any positive sentiment/intent from SmartLead AI classification
    # These indicate the lead is warm and worth following up
    POSITIVE_CATEGORIES = {'Interested', 'Meeting Request', 'Meeting Booked', 'Information Request'}

    replied_records = [s for s in stats_list if s.get('reply_time') is not None]
    positive_replies = sum(1 for s in replied_records if s.get('lead_category') in POSITIVE_CATEGORIES)

    return {
        'sent': len(stats_list),
        'opened': sum(1 for s in stats_list if s.get('open_count', 0) > 0),
        'clicked': sum(1 for s in stats_list if s.get('click_count', 0) > 0),
        'replied': len(replied_records),
        'positive': positive_replies,  # From lead_category, not all-time analytics
        'bounced': sum(1 for s in stats_list if s.get('is_bounced')),
        'unsubscribed': sum(1 for s in stats_list if s.get('is_unsubscribed')),
    }

def print_campaign_summary():
    """Print summary of all campaigns with all-time stats."""
    print("\n" + "="*80)
    print("SMARTLEAD CAMPAIGN SUMMARY (ALL-TIME)")
    print("="*80)

    campaigns = get_all_campaigns()

    plg_totals = defaultdict(int)
    other_totals = defaultdict(int)

    print(f"\n{'Campaign Name':<50} {'Status':<10} {'Sent':>10} {'Replies':>10} {'Reply%':>8}")
    print("-"*90)

    for camp in sorted(campaigns, key=lambda x: x['name']):
        try:
            analytics = get_campaign_analytics(camp['id'])
            sent = int(analytics.get('sent_count', 0) or 0)
            replies = int(analytics.get('reply_count', 0) or 0)
            reply_rate = (replies / sent * 100) if sent > 0 else 0

            name = camp['name'][:48]
            status = camp['status']

            print(f"{name:<50} {status:<10} {sent:>10,} {replies:>10,} {reply_rate:>7.1f}%")

            # Aggregate by PLG vs non-PLG
            target = plg_totals if is_plg_campaign(camp['name']) else other_totals
            target['sent'] += sent
            target['replies'] += replies
            target['interested'] += analytics.get('campaign_lead_stats', {}).get('interested', 0) or 0
            target['bounced'] += int(analytics.get('bounce_count', 0) or 0)
            target['campaigns'] += 1

        except Exception as e:
            print(f"{camp['name'][:48]:<50} ERROR: {e}")

    print("\n" + "-"*90)
    print("\nAGGREGATED BY TYPE:")
    print("-"*50)

    for label, totals in [("PLG (Internal Marketing)", plg_totals), ("Other Campaigns", other_totals)]:
        if totals['campaigns'] > 0:
            reply_rate = (totals['replies'] / totals['sent'] * 100) if totals['sent'] > 0 else 0
            print(f"\n{label}:")
            print(f"  Campaigns: {totals['campaigns']}")
            print(f"  Emails Sent: {totals['sent']:,}")
            print(f"  Replies: {totals['replies']:,}")
            print(f"  Reply Rate: {reply_rate:.2f}%")
            print(f"  Interested Leads: {totals['interested']:,}")
            print(f"  Bounced: {totals['bounced']:,}")

def print_weekly_stats(start_date=None, end_date=None):
    """Print stats for a specific week by filtering sent_time."""
    if start_date is None:
        sunday, saturday = get_week_bounds()
        start_date = sunday.strftime("%Y-%m-%d")
        end_date = saturday.strftime("%Y-%m-%d")

    print("\n" + "="*80)
    print(f"SMARTLEAD WEEKLY STATS: {start_date} to {end_date}")
    print("="*80)

    campaigns = get_all_campaigns()

    plg_totals = defaultdict(int)
    other_totals = defaultdict(int)

    print(f"\n{'Campaign Name':<45} {'Sent':>8} {'Opens':>8} {'Replies':>8} {'Reply%':>8}")
    print("-"*85)

    for camp in sorted(campaigns, key=lambda x: x['name']):
        if camp['status'] not in ['ACTIVE', 'PAUSED', 'COMPLETED']:
            continue

        try:
            # Get detailed stats with date filtering via API
            stats_list = get_campaign_statistics(camp['id'], start_date, end_date)
            agg = aggregate_stats(stats_list)

            if agg['sent'] == 0:
                continue

            reply_rate = (agg['replied'] / agg['sent'] * 100) if agg['sent'] > 0 else 0
            name = camp['name'][:43]

            print(f"{name:<45} {agg['sent']:>8,} {agg['opened']:>8,} {agg['replied']:>8,} {reply_rate:>7.1f}%")

            # Aggregate
            target = plg_totals if is_plg_campaign(camp['name']) else other_totals
            for k, v in agg.items():
                target[k] += v
            target['campaigns'] += 1

        except Exception as e:
            print(f"{camp['name'][:43]:<45} ERROR: {e}")

    print("\n" + "-"*85)
    print("\nWEEKLY TOTALS BY TYPE:")
    print("-"*50)

    for label, totals in [("PLG (Internal Marketing)", plg_totals), ("Other Campaigns", other_totals)]:
        if totals.get('sent', 0) > 0:
            reply_rate = (totals['replied'] / totals['sent'] * 100) if totals['sent'] > 0 else 0
            open_rate = (totals['opened'] / totals['sent'] * 100) if totals['sent'] > 0 else 0
            print(f"\n{label}:")
            print(f"  Campaigns Active: {totals.get('campaigns', 0)}")
            print(f"  Emails Sent: {totals['sent']:,}")
            print(f"  Opened: {totals['opened']:,} ({open_rate:.1f}%)")
            print(f"  Replied: {totals['replied']:,} ({reply_rate:.2f}%)")
            print(f"  Bounced: {totals['bounced']:,}")

    # Return totals for integration
    return {
        'plg': dict(plg_totals),
        'other': dict(other_totals),
        'start_date': start_date,
        'end_date': end_date
    }

def get_weekly_summary(start_date=None, end_date=None):
    """Get weekly SmartLead stats as a dict for dashboard integration.

    Note: positive_replies is now derived from lead_category in weekly data,
    NOT from all-time campaign_lead_stats.interested (which was the bug).
    """
    if start_date is None:
        sunday, saturday = get_week_bounds()
        start_date = sunday.strftime("%Y-%m-%d")
        end_date = saturday.strftime("%Y-%m-%d")

    campaigns = get_all_campaigns()

    plg_totals = defaultdict(int)
    other_totals = defaultdict(int)

    for camp in campaigns:
        if camp['status'] not in ['ACTIVE', 'PAUSED', 'COMPLETED']:
            continue
        try:
            stats_list = get_campaign_statistics(camp['id'], start_date, end_date)
            agg = aggregate_stats(stats_list)
            if agg['sent'] == 0:
                continue

            target = plg_totals if is_plg_campaign(camp['name']) else other_totals
            for k, v in agg.items():
                target[k] += v
            target['campaigns'] += 1
        except:
            pass

    def calc_rate(num, denom):
        return (num / denom * 100) if denom > 0 else 0

    return {
        'start_date': start_date,
        'end_date': end_date,
        'plg': {
            'emails_sent': plg_totals['sent'],
            'replies': plg_totals['replied'],
            'reply_rate': calc_rate(plg_totals['replied'], plg_totals['sent']),
            'positive_replies': plg_totals['positive'],  # Now from lead_category, weekly
            'positive_rate': calc_rate(plg_totals['positive'], plg_totals['sent']),
            'bounced': plg_totals['bounced'],
            'campaigns': plg_totals['campaigns'],
        },
        'outbound': {
            'emails_sent': other_totals['sent'],
            'replies': other_totals['replied'],
            'reply_rate': calc_rate(other_totals['replied'], other_totals['sent']),
            'positive_replies': other_totals['positive'],  # Now from lead_category, weekly
            'positive_rate': calc_rate(other_totals['positive'], other_totals['sent']),
            'bounced': other_totals['bounced'],
            'campaigns': other_totals['campaigns'],
        },
        'total': {
            'emails_sent': plg_totals['sent'] + other_totals['sent'],
            'replies': plg_totals['replied'] + other_totals['replied'],
            'positive_replies': plg_totals['positive'] + other_totals['positive'],
        }
    }


def get_plg_campaign_breakdown(start_date=None, end_date=None):
    """Get per-campaign breakdown for PLG campaigns.

    Returns list of dicts with campaign name, emails, replies, positive, reply_rate.
    Sorted by emails sent descending.
    """
    if start_date is None:
        sunday, saturday = get_week_bounds()
        start_date = sunday.strftime("%Y-%m-%d")
        end_date = saturday.strftime("%Y-%m-%d")

    campaigns = get_all_campaigns()
    campaign_stats = []

    for camp in campaigns:
        if not is_plg_campaign(camp['name']):
            continue
        if camp['status'] not in ['ACTIVE', 'PAUSED', 'COMPLETED']:
            continue
        try:
            stats_list = get_campaign_statistics(camp['id'], start_date, end_date)
            agg = aggregate_stats(stats_list)
            if agg['sent'] == 0:
                continue

            reply_rate = (agg['replied'] / agg['sent'] * 100) if agg['sent'] > 0 else 0
            positive_rate = (agg['positive'] / agg['sent'] * 100) if agg['sent'] > 0 else 0

            campaign_stats.append({
                'name': camp['name'],
                'status': camp['status'],
                'emails': agg['sent'],
                'replies': agg['replied'],
                'positive': agg['positive'],
                'reply_rate': reply_rate,
                'positive_rate': positive_rate,
            })
        except:
            pass

    # Sort by emails sent descending
    return sorted(campaign_stats, key=lambda x: x['emails'], reverse=True)


def get_plg_category_breakdown(start_date=None, end_date=None):
    """Get PLG stats grouped by campaign category.

    Extracts category from campaign name (e.g., "PLG - IT Solutions" -> "IT Solutions").
    Returns list of dicts with category, emails, positive replies, rate.
    """
    import re

    campaign_stats = get_plg_campaign_breakdown(start_date, end_date)
    category_totals = defaultdict(lambda: {'emails': 0, 'replies': 0, 'positive': 0})

    for camp in campaign_stats:
        # Extract category from "PLG - Category Name" pattern
        match = re.match(r'PLG\s*-\s*(.+)', camp['name'], re.IGNORECASE)
        category = match.group(1).strip() if match else 'Other'
        # Clean up duplicates like "copy" suffix
        category = re.sub(r'\s*-?\s*copy\d*$', '', category, flags=re.IGNORECASE)

        category_totals[category]['emails'] += camp['emails']
        category_totals[category]['replies'] += camp['replies']
        category_totals[category]['positive'] += camp['positive']

    result = []
    for category, totals in category_totals.items():
        positive_rate = (totals['positive'] / totals['emails'] * 100) if totals['emails'] > 0 else 0
        result.append({
            'category': category,
            'emails': totals['emails'],
            'replies': totals['replies'],
            'positive': totals['positive'],
            'positive_rate': positive_rate,
        })

    # Sort by emails sent descending
    return sorted(result, key=lambda x: x['emails'], reverse=True)


def main():
    """Main entry point."""
    if len(sys.argv) == 1:
        # No args - show all-time summary
        print_campaign_summary()
        print("\n" + "="*80)
        print("For weekly stats, run: python3 smartlead_pull.py 2026-01-19 2026-01-25")
        print("="*80)
    elif len(sys.argv) == 2 and sys.argv[1] == '--week':
        # Last complete week
        print_weekly_stats()
    elif len(sys.argv) == 3:
        # Specific date range
        start_date, end_date = sys.argv[1], sys.argv[2]
        print_weekly_stats(start_date, end_date)
    else:
        print("Usage:")
        print("  python3 smartlead_pull.py              # All-time summary")
        print("  python3 smartlead_pull.py --week       # Last complete week")
        print("  python3 smartlead_pull.py START END    # Specific date range")

if __name__ == "__main__":
    main()
