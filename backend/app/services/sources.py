"""Definitions of the demo evidence sources. All are simulated, and labelled so everywhere."""

SOURCE_DEFINITIONS = [
    {
        "key": "idp_auth",
        "name": "Authentication logs",
        "description": "Identity provider sign-ins, failures and MFA steps.",
        "permissions": ["idp_auth:read"],
    },
    {
        "key": "edr",
        "name": "Endpoint detection records",
        "description": "EDR telemetry batches and detections from enrolled agents.",
        "permissions": ["edr:read"],
    },
    {
        "key": "network",
        "name": "Network activity",
        "description": "Hourly per-host traffic summaries from network sensors.",
        "permissions": ["network:read"],
    },
    {
        "key": "inventory",
        "name": "Device inventory",
        "description": "The asset register of in-scope hosts.",
        "permissions": ["inventory:read"],
    },
    {
        "key": "coverage",
        "name": "Monitoring coverage",
        "description": "EDR enrollment state and last heartbeat per host.",
        "permissions": ["coverage:read"],
    },
    {
        "key": "directory",
        "name": "Directory and VPN records",
        "description": "Domain-controller logons, VPN sessions and approved changes, recorded independently of the "
        "identity provider.",
        "permissions": ["directory:read"],
        "restricted": True,
    },
]

# Listed so the gap shows up. It has no records and is disconnected.
UNCONNECTED_SOURCES = [
    {
        "key": "saas_audit",
        "name": "SaaS audit trail",
        "description": "Administrative activity from third-party SaaS applications. Never connected in this workspace.",
        "permissions": ["saas_audit:read"],
    },
]

ALL_SOURCE_KEYS = [s["key"] for s in SOURCE_DEFINITIONS]
