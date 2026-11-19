from __future__ import annotations

from typing import List, Mapping, Optional

import httpx

from delivery_analysis.connectors.base import Connector
from delivery_analysis.connectors.bitbucket.client import BitbucketClient
from delivery_analysis.connectors.bitbucket.connector import BitbucketConnector
from delivery_analysis.connectors.claude_code.client import ClaudeCodeClient, usage_key
from delivery_analysis.connectors.claude_code.connector import ClaudeCodeConnector
from delivery_analysis.connectors.jira.client import JiraClient, base_url_from, jira_credentials
from delivery_analysis.connectors.jira.connector import JiraConnector
from delivery_analysis.settings import Settings


def build_connectors(
    settings: Settings,
    environ: Mapping[str, str],
    transport: Optional[httpx.BaseTransport] = None,
) -> List[Connector]:
    """Confluence arrives in a later spec."""
    connectors: List[Connector] = []
    token = (environ.get("BITBUCKET") or "").strip()
    if token:
        client = BitbucketClient(token, transport=transport, budget=settings.bitbucket_budget,
                                 patience=settings.bitbucket_patience_hours * 3600.0)
        connectors.append(
            BitbucketConnector(
                client,
                settings.db_path,
                workspace=settings.bitbucket_workspace,
                window_days=settings.window_days,
            )
        )
    if (environ.get("ATLASSIAN") or "").strip():
        email, secret = jira_credentials(environ)
        jira_client = JiraClient(email, secret, base_url=base_url_from(environ), transport=transport)
        connectors.append(JiraConnector(jira_client, settings.db_path, window_days=settings.window_days))
    claude_key = usage_key(environ)
    if claude_key:
        connectors.append(
            ClaudeCodeConnector(
                ClaudeCodeClient(claude_key, transport=transport),
                report="user_cost",
                window_days=settings.window_days,
            )
        )
    return connectors
