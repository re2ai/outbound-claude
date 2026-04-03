import json, re, random
from datetime import datetime, timezone
from google.cloud import bigquery

client = bigquery.Client(project='tenant-recruitin-1575995920662')
NOW = datetime.now(timezone.utc).isoformat()

with open('C:/Users/evane/Documents/hvac_emails_clean.json', encoding='utf-8') as f:
    leads = json.load(f)

# Reproduce same 760/759 split (seed 42)
random.seed(42)
random.shuffle(leads)
oe_emails = {l['email'] for l in leads[:760]}

def to_row(lead):
    email = lead.get('email', '')
    if email in oe_emails:
        campaign_id   = 3124982
        campaign_name = 'PLG - HVAC - Email - DataDriven - Access - OtherEmails'
        ab_variant    = 'OtherEmails'
    else:
        campaign_id   = 3124974
        campaign_name = 'PLG - HVAC - Email - DataDriven - Access - MSList'
        ab_variant    = 'MSList'

    return {
        'apollo_id':               lead.get('apollo_id'),
        'first_name':              lead.get('first_name'),
        'last_name':               lead.get('last_name'),
        'email':                   email,
        'email_status':            None,
        'title':                   lead.get('title'),
        'headline':                None,
        'seniority':               None,
        'departments':             None,
        'city':                    lead.get('city'),
        'state':                   lead.get('state'),
        'country':                 None,
        'linkedin_url':            lead.get('linkedin_url'),
        'photo_url':               None,
        'twitter_url':             None,
        'facebook_url':            None,
        'company_name':            lead.get('company_name'),
        'company_domain':          lead.get('company_domain'),
        'company_website':         None,
        'company_linkedin_url':    None,
        'company_phone':           None,
        'company_city':            None,
        'company_state':           None,
        'company_country':         None,
        'company_address':         None,
        'company_industry':        None,
        'company_keywords':        None,
        'company_short_description': None,
        'company_num_employees':   None,
        'company_annual_revenue':  None,
        'company_founded_year':    None,
        'company_facebook_url':    None,
        'company_twitter_url':     None,
        'company_sic_codes':       None,
        'company_naics_codes':     None,
        'company_technologies':    None,
        'segment':                 'hvac',
        'apollo_keyword':          lead.get('keyword') or 'commercial hvac',
        'campaign_name':           campaign_name,
        'stage':                   'enrolled',
        'discovered_at':           NOW,
        'enriched_at':             NOW,
        'created_at':              NOW,
        'sl_individual_match':     None,
        'sl_individual_detail':    None,
        'sl_domain_match':         None,
        'sl_domain_detail':        None,
        'hs_individual_match':     None,
        'hs_individual_detail':    None,
        'hs_domain_match':         None,
        'hs_domain_detail':        None,
        'bq_previously_enriched':  None,
        'bq_enriched_detail':      None,
        'email_verified':          bool(lead.get('_bv_deliverable', True)),
        'verification_status':     lead.get('_bv_status'),
        'web_enrichment':          None,
        'subject1':                lead.get('Subject1'),
        'subject3':                lead.get('Subject3'),
        'email1':                  lead.get('Email1'),
        'email2':                  lead.get('Email2'),
        'email3':                  lead.get('Email3'),
        'city_resolved':           lead.get('city_resolved'),
        'businesses_str':          lead.get('businesses_str'),
        'source':                  lead.get('source'),
        'smartlead_campaign_id':   campaign_id,
        'enrolled_at':             NOW,
        'ab_variant':              ab_variant,
        'updated_at':              NOW,
    }

rows = [to_row(l) for l in leads]

TABLE_ID = 'tenant-recruitin-1575995920662.PLG_OUTBOUND.hvac_20260403_v1'

schema = [
    bigquery.SchemaField('apollo_id', 'STRING'),
    bigquery.SchemaField('first_name', 'STRING'),
    bigquery.SchemaField('last_name', 'STRING'),
    bigquery.SchemaField('email', 'STRING'),
    bigquery.SchemaField('email_status', 'STRING'),
    bigquery.SchemaField('title', 'STRING'),
    bigquery.SchemaField('headline', 'STRING'),
    bigquery.SchemaField('seniority', 'STRING'),
    bigquery.SchemaField('departments', 'STRING'),
    bigquery.SchemaField('city', 'STRING'),
    bigquery.SchemaField('state', 'STRING'),
    bigquery.SchemaField('country', 'STRING'),
    bigquery.SchemaField('linkedin_url', 'STRING'),
    bigquery.SchemaField('photo_url', 'STRING'),
    bigquery.SchemaField('twitter_url', 'STRING'),
    bigquery.SchemaField('facebook_url', 'STRING'),
    bigquery.SchemaField('company_name', 'STRING'),
    bigquery.SchemaField('company_domain', 'STRING'),
    bigquery.SchemaField('company_website', 'STRING'),
    bigquery.SchemaField('company_linkedin_url', 'STRING'),
    bigquery.SchemaField('company_phone', 'STRING'),
    bigquery.SchemaField('company_city', 'STRING'),
    bigquery.SchemaField('company_state', 'STRING'),
    bigquery.SchemaField('company_country', 'STRING'),
    bigquery.SchemaField('company_address', 'STRING'),
    bigquery.SchemaField('company_industry', 'STRING'),
    bigquery.SchemaField('company_keywords', 'STRING'),
    bigquery.SchemaField('company_short_description', 'STRING'),
    bigquery.SchemaField('company_num_employees', 'INTEGER'),
    bigquery.SchemaField('company_annual_revenue', 'FLOAT'),
    bigquery.SchemaField('company_founded_year', 'INTEGER'),
    bigquery.SchemaField('company_facebook_url', 'STRING'),
    bigquery.SchemaField('company_twitter_url', 'STRING'),
    bigquery.SchemaField('company_sic_codes', 'STRING'),
    bigquery.SchemaField('company_naics_codes', 'STRING'),
    bigquery.SchemaField('company_technologies', 'STRING'),
    bigquery.SchemaField('segment', 'STRING'),
    bigquery.SchemaField('apollo_keyword', 'STRING'),
    bigquery.SchemaField('campaign_name', 'STRING'),
    bigquery.SchemaField('stage', 'STRING'),
    bigquery.SchemaField('discovered_at', 'TIMESTAMP'),
    bigquery.SchemaField('enriched_at', 'TIMESTAMP'),
    bigquery.SchemaField('created_at', 'TIMESTAMP'),
    bigquery.SchemaField('sl_individual_match', 'BOOLEAN'),
    bigquery.SchemaField('sl_individual_detail', 'STRING'),
    bigquery.SchemaField('sl_domain_match', 'BOOLEAN'),
    bigquery.SchemaField('sl_domain_detail', 'STRING'),
    bigquery.SchemaField('hs_individual_match', 'BOOLEAN'),
    bigquery.SchemaField('hs_individual_detail', 'STRING'),
    bigquery.SchemaField('hs_domain_match', 'BOOLEAN'),
    bigquery.SchemaField('hs_domain_detail', 'STRING'),
    bigquery.SchemaField('bq_previously_enriched', 'BOOLEAN'),
    bigquery.SchemaField('bq_enriched_detail', 'STRING'),
    bigquery.SchemaField('email_verified', 'BOOLEAN'),
    bigquery.SchemaField('verification_status', 'STRING'),
    bigquery.SchemaField('web_enrichment', 'STRING'),
    bigquery.SchemaField('subject1', 'STRING'),
    bigquery.SchemaField('subject3', 'STRING'),
    bigquery.SchemaField('email1', 'STRING'),
    bigquery.SchemaField('email2', 'STRING'),
    bigquery.SchemaField('email3', 'STRING'),
    bigquery.SchemaField('city_resolved', 'STRING'),
    bigquery.SchemaField('businesses_str', 'STRING'),
    bigquery.SchemaField('source', 'STRING'),
    bigquery.SchemaField('smartlead_campaign_id', 'INTEGER'),
    bigquery.SchemaField('enrolled_at', 'TIMESTAMP'),
    bigquery.SchemaField('ab_variant', 'STRING'),
    bigquery.SchemaField('updated_at', 'TIMESTAMP'),
]

table = bigquery.Table(TABLE_ID, schema=schema)
table = client.create_table(table, exists_ok=True)
print(f'Table ready: {TABLE_ID}')

batch_size = 500
for i in range(0, len(rows), batch_size):
    batch = rows[i:i+batch_size]
    errors = client.insert_rows_json(TABLE_ID, batch)
    if errors:
        print(f'  Batch {i//batch_size+1} errors: {errors[:2]}')
    else:
        print(f'  Batch {i//batch_size+1}: {len(batch)} rows inserted')

print(f'Done. {len(rows)} total rows written.')
