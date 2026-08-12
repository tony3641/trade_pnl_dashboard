"""Keep the shared initial-capital total in sync with the per-account capital map.

``app.py`` treats the per-account ``account_capital`` map as the source of
truth and recomputes the shared initial-capital total (used by the Curve /
Risk tabs) as the sum of per-account initials on every rerun.  When a user
edits that shared total directly in the Curve / Risk tabs, this helper writes
the edit back into the map so the two never drift.
"""

from __future__ import annotations

import streamlit as st


def sync_shared_capital_to_account_map(total: float) -> None:
    """Write the shared initial-capital total back to the per-account map.

    With a single account the edited total becomes that account's initial
    capital.  With multiple accounts it is redistributed proportionally so the
    map still sums to the total.
    """
    acct_cap = st.session_state.get("account_capital")
    if not acct_cap:
        return
    entries = [v for v in acct_cap.values() if v.get("initial")]
    if len(entries) == 1:
        entries[0]["initial"] = float(total)
    elif entries:
        sum0 = sum(float(v.get("initial") or 0.0) for v in entries)
        if sum0 > 0:
            ratio = float(total) / sum0
            for v in entries:
                v["initial"] = float(v.get("initial") or 0.0) * ratio
    st.session_state["account_capital"] = acct_cap
