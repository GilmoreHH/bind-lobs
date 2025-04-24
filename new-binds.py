import streamlit as st
from simple_salesforce import Salesforce
import os
from dotenv import load_dotenv
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import datetime
import numpy as np

# Load environment variables from .env file
load_dotenv()

st.set_page_config(
    page_title="New Binds Analysis Dashboard",
    page_icon="📊",
    layout="wide",
)

# ==============================================================================
# Authentication Section
# ==============================================================================
if "sf_connected" not in st.session_state:
    st.session_state.sf_connected = False

# Display an authentication button at the top.
if not st.session_state.sf_connected:
    if st.button("Authenticate to Salesforce"):
        try:
            sf = Salesforce(
                username=os.getenv("SF_USERNAME_PRO"),
                password=os.getenv("SF_PASSWORD_PRO"),
                security_token=os.getenv("SF_SECURITY_TOKEN_PRO")
            )
            st.session_state.sf = sf
            st.session_state.sf_connected = True
            st.success("Connected to Salesforce!")
        except Exception as e:
            st.error(f"Error connecting to Salesforce: {e}")
    else:
        st.info("Click the button above to authenticate to Salesforce.")
        st.stop()  # Stop further execution until authentication is successful.

# ==============================================================================
# Utility Functions and Queries
# ==============================================================================

# -------------------------------------------------------------
# UPDATED Expanded LOB_MAPPING - with additional types going to Homeowners
# -------------------------------------------------------------
LOB_MAPPING = {
    # HOMEOWNERS
    "Homeowners": "Homeowners",
    "Dwelling Fire - PL": "Homeowners",
    "Mobile Homeowners": "Homeowners",
    "Wind Only - PL": "Homeowners",
    "Flood - PL": "Homeowners",  # Changed "Other" to "Homeowners"
    "Builders Risk/Installation - PL": "Homeowners",  # Changed from "Commercial" to "Homeowners"
    "Dwelling": "Homeowners",  # Added 
    
    # PERSONAL AUTO
    "Personal Auto": "Personal Auto",
    "Motorcycle/ATV": "Personal Auto",
    "Motorhome": "Personal Auto",
    "Recreational Vehicle": "Personal Auto",
    "Travel Trailer": "Personal Auto",
    "Golf Cart": "Personal Auto",
    
    # BOAT
    "Watercraft": "Boat",
    "Charter Watercraft": "Boat",
    "Yacht": "Boat",
    "Burnboat": "Boat",
    "Boat": "Boat",
    
    # UMBRELLA
    "Umbrella": "Umbrella",
    "Commercial Umbrella": "Umbrella",
    
    # INLAND MARINE
    "Inland Marine - PL": "Inland Marine",
    "Inland Marine - CL": "Inland Marine",
    
    # COMMERCIAL
    "Commercial Package": "Commercial",
    "Builders Risk/Installation - CL": "Commercial",
    "Business Owners": "Commercial",
    "Commercial Auto": "Commercial",
    "Commercial Property": "Commercial",
    "Directors & Officers": "Commercial",
    "Employment Practice Liability": "Commercial",
    "Errors & Omissions": "Commercial",
    "General Liability": "Commercial",
    "Liquor Liability": "Commercial",
    "Marine Package": "Commercial",
    "Wind Only - CL": "Commercial",
    
    # EVERYTHING ELSE
    "Personal Liability": "Other",
    "Life": "Other",
    # If new picklist values appear in the future, you can map them here too.
}

def map_lob(type_value: str) -> str:
    """Return the LOB category or 'Other' if not defined in LOB_MAPPING."""
    return LOB_MAPPING.get(type_value, "Other")

def get_producer_names(sf, producer_ids):
    """
    Given a list of Producer IDs (from ProducerId on Opportunity),
    query the Producer object to retrieve the associated user's first and last name.
    The Producer record is linked to a User via the InternalUser lookup.
    Returns a dict mapping Producer ID -> "FirstName LastName".
    """
    if not producer_ids:
        return {}
    # Build comma-separated list for SOQL (each id enclosed in single quotes)
    id_list = ", ".join(f"'{pid}'" for pid in producer_ids)
    query = f"""
        SELECT Id, InternalUser.FirstName, InternalUser.LastName
        FROM Producer
        WHERE Id IN ({id_list})
    """
    results = sf.query_all(query)
    mapping = {}
    for rec in results["records"]:
        pid = rec.get("Id")
        # Safely access the InternalUser relationship.
        internal_user = rec.get("InternalUser") or {}
        first = internal_user.get("FirstName", "")
        last = internal_user.get("LastName", "")
        full_name = f"{first} {last}".strip()
        if not full_name:
            full_name = "Name Not Provided"
        mapping[pid] = full_name
    return mapping

def connect_sf_and_query(start_date, end_date, new_business_only):
    """
    Uses an authenticated Salesforce connection (stored in st.session_state.sf)
    to run three sets of queries:
      1) Overall aggregation by Type (for LOB summary).
      2) Policies with ProducerId populated (grouped by ProducerId and Type).
      3) Policies without ProducerId (fallback to Owner.Name, grouped by Type).
    For policies with a Producer, it retrieves the full name from the Producer object.
    """
    try:
        sf = st.session_state.sf  # Use the authenticated connection
        
        # Format dates as DateTime literals.
        start_date_str = start_date.strftime('%Y-%m-%dT00:00:00Z')
        end_date_str = end_date.strftime('%Y-%m-%dT23:59:59Z')
        date_filter = f"CreatedDate >= {start_date_str} AND CreatedDate <= {end_date_str}"
        
        # Add New Business filter if checkbox is selected - UPDATED to use Business_Type_Reporting__c
        if new_business_only:
            new_business_filter = "AND Business_Type_Reporting__c = 'New Business'"
        else:
            new_business_filter = ""
        
        # Query 1: Overall aggregation by Type.
        type_query = f"""
            SELECT PolicyType, COUNT(Id) policyCount
            FROM InsurancePolicy
            WHERE {date_filter} {new_business_filter}
            GROUP BY PolicyType
        """
        type_results = sf.query_all(type_query)
        lob_data = []
        for rec in type_results["records"]:
            picklist_val = rec.get("PolicyType", "Other")
            count_val = rec.get("policyCount", 0)
            lob_category = map_lob(picklist_val)
            lob_data.append({
                "Type": picklist_val,
                "LOB_Category": lob_category,
                "Count": count_val
            })
        lob_df = pd.DataFrame(lob_data)
        
        # Query 2: Policies with ProducerId populated.
        query_with_producer = f"""
            SELECT ProducerId, PolicyType, COUNT(Id) policyCount
            FROM InsurancePolicy
            WHERE {date_filter} {new_business_filter} AND ProducerId != null
            GROUP BY ProducerId, PolicyType
        """
        results_with_prod = sf.query_all(query_with_producer)
        
        # Query 3: Policies without ProducerId (use Owner.Name as fallback).
        query_without_producer = f"""
            SELECT Owner.Name, PolicyType, COUNT(Id) policyCount
            FROM InsurancePolicy
            WHERE {date_filter} {new_business_filter} AND ProducerId = null
            GROUP BY Owner.Name, PolicyType
        """
        results_without_prod = sf.query_all(query_without_producer)
        
        # Gather unique ProducerId IDs from Query 2.
        producer_ids = { rec.get("ProducerId") for rec in results_with_prod["records"] if rec.get("ProducerId") }
        producer_names = get_producer_names(sf, list(producer_ids))
        
        producer_data = []
        # Process results from Query 2 (with ProducerId).
        for rec in results_with_prod["records"]:
            prod_id = rec.get("ProducerId")
            producer_name = producer_names.get(prod_id, "Name Not Provided")
            picklist_val = rec.get("PolicyType", "Other")
            count_val = rec.get("policyCount", 0)
            lob_category = map_lob(picklist_val)
            producer_data.append({
                "Producer": producer_name,
                "Type": picklist_val,
                "LOB_Category": lob_category,
                "Count": count_val
            })
        # Process results from Query 3 (fallback using Owner.Name).
        for rec in results_without_prod["records"]:
            owner = rec.get("Owner") or {}
            producer_name = owner.get("Name", "Name Not Provided")
            picklist_val = rec.get("PolicyType", "Other")
            count_val = rec.get("policyCount", 0)
            lob_category = map_lob(picklist_val)
            producer_data.append({
                "Producer": producer_name,
                "Type": picklist_val,
                "LOB_Category": lob_category,
                "Count": count_val
            })
        producer_df = pd.DataFrame(producer_data)
        
        return lob_df, producer_df
        
    except Exception as e:
        st.error(f"Error connecting to Salesforce: {e}")
        return pd.DataFrame(), pd.DataFrame()

# ==============================================================================
# Streamlit UI for Date Selection and Visualizations
# ==============================================================================

st.title("Policy Analysis Dashboard")

# Sidebar: Date Range Selection and New Business Filter
st.sidebar.header("Dashboard Options")
today = datetime.date.today()
start_date = st.sidebar.date_input("Start Date", today - datetime.timedelta(days=30))
end_date = st.sidebar.date_input("End Date", today)

# Add checkbox for New Business filter - UPDATED HELP TEXT
new_business_only = st.sidebar.checkbox("New Business Only", value=False, 
                                       help="Filter for policies where Business_Type_Reporting__c = 'New Business'")

# Retrieve data using the authenticated Salesforce connection.
lob_df, producer_df = connect_sf_and_query(start_date, end_date, new_business_only)

# Visualization 1: Overall LOB distribution.
st.subheader("Policies by Line of Business Category")
if not lob_df.empty:
    grouped_lob = lob_df.groupby("LOB_Category")["Count"].sum().reset_index()
    fig_lob = px.pie(
        grouped_lob,
        names="LOB_Category",
        values="Count",
        title="Policy Distribution by LOB Category"
    )
    st.plotly_chart(fig_lob)
    st.dataframe(grouped_lob)
else:
    st.info("No Line of Business data available for the selected date range.")

# Visualization 2: Policies per Producer by LOB.
st.subheader("Policies per Producer by LOB Category")
if not producer_df.empty:
    grouped_producer = producer_df.groupby(["Producer", "LOB_Category"])["Count"].sum().reset_index()
    fig_prod = px.bar(
        grouped_producer,
        x="Producer",
        y="Count",
        color="LOB_Category",
        barmode="group",
        title="Policies per Producer by LOB"
    )
    st.plotly_chart(fig_prod)
    st.dataframe(grouped_producer)
else:
    st.info("No producer data available for the selected date range.")

# Optionally, show raw data.
if st.sidebar.checkbox("Show Raw Data"):
    st.subheader("Raw Data (Overall LOB)")
    st.dataframe(lob_df)
    st.subheader("Raw Data (Producer)")
    st.dataframe(producer_df)
