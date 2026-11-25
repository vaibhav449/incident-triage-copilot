"""Streamlit UI (owner: Member 1). Run with `make dev-ui`."""

import streamlit as st

st.set_page_config(page_title="Incident-Triage Copilot")
st.title("Incident-Triage Copilot")
st.info(
    "Placeholder. The triage view (ranked causes, clickable citations, approve/reject fix) "
    "arrives in Weeks 7–8 once the API serves POST /v1/triage."
)
