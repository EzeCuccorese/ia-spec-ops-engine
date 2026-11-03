"""Real GitHub responses captured read-only (2026-11, gh 2.103) and kept as the contract.

Each constant is the exact JSON gh api graphql / gh auth status --json hosts printed for
the queries in ai_governance.taskflow.prs.github. Nothing secret is in them: public repository
facts and account logins only. test_prs_github checks that the fake gh replays exactly
these envelopes, so the fake cannot drift from what GitHub returns.
"""

from __future__ import annotations

REPO = "EzeCuccorese/ia-spec-ops-engine"
# first: 2 pages of review threads, to prove the cursor flow with a real endCursor
OPEN_DRAFT_49 = {
    "data": {
        "repository": {
            "defaultBranchRef": {"name": "main"},
            "pullRequest": {
                "state": "OPEN",
                "isDraft": True,
                "baseRefName": "main",
                "headRefName": "feat-taskflow-pr-board",
                "mergeable": "MERGEABLE",
                "reviewDecision": None,
                "title": "feat(taskflow): Orca-run reader rounds, per-repo allowed agents, PR board, missing-repo fix",
                "headRepository": {"nameWithOwner": "EzeCuccorese/ia-spec-ops-engine"},
                "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "PENDING"}}}]},
                "reviewThreads": {
                    "totalCount": 0,
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [],
                },
            },
        }
    }
}

MERGED_47 = {
    "data": {
        "repository": {
            "defaultBranchRef": {"name": "main"},
            "pullRequest": {
                "state": "MERGED",
                "isDraft": False,
                "baseRefName": "main",
                "headRefName": "feat-config-flex",
                "mergeable": "UNKNOWN",
                "reviewDecision": None,
                "title": "feat(config): layered configuration, repo-priority controls with trust, and module splits",
                "headRepository": {"nameWithOwner": "EzeCuccorese/ia-spec-ops-engine"},
                "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "SUCCESS"}}}]},
                "reviewThreads": {
                    "totalCount": 4,
                    "pageInfo": {
                        "hasNextPage": False,
                        "endCursor": "Y3Vyc29yOnYyOpK0MjAyNi0xMS0wM1QxNjo0NToyOVrOszubRA==",
                    },
                    "nodes": [
                        {"isResolved": True},
                        {"isResolved": True},
                        {"isResolved": True},
                        {"isResolved": True},
                    ],
                },
            },
        }
    }
}

THREADS_PAGE_1 = {
    "data": {
        "repository": {
            "defaultBranchRef": {"name": "main"},
            "pullRequest": {
                "state": "MERGED",
                "isDraft": False,
                "baseRefName": "main",
                "headRefName": "feat-config-flex",
                "mergeable": "UNKNOWN",
                "reviewDecision": None,
                "title": "feat(config): layered configuration, repo-priority controls with trust, and module splits",
                "headRepository": {"nameWithOwner": "EzeCuccorese/ia-spec-ops-engine"},
                "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "SUCCESS"}}}]},
                "reviewThreads": {
                    "totalCount": 4,
                    "pageInfo": {
                        "hasNextPage": True,
                        "endCursor": "Y3Vyc29yOnYyOpK0MjAyNi0xMS0wM1QxNjo0NToyOVrOszubLQ==",
                    },
                    "nodes": [{"isResolved": True}, {"isResolved": True}],
                },
            },
        }
    }
}

THREADS_PAGE_2 = {
    "data": {
        "repository": {
            "defaultBranchRef": {"name": "main"},
            "pullRequest": {
                "state": "MERGED",
                "isDraft": False,
                "baseRefName": "main",
                "headRefName": "feat-config-flex",
                "mergeable": "UNKNOWN",
                "reviewDecision": None,
                "title": "feat(config): layered configuration, repo-priority controls with trust, and module splits",
                "headRepository": {"nameWithOwner": "EzeCuccorese/ia-spec-ops-engine"},
                "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "SUCCESS"}}}]},
                "reviewThreads": {
                    "totalCount": 4,
                    "pageInfo": {
                        "hasNextPage": False,
                        "endCursor": "Y3Vyc29yOnYyOpK0MjAyNi0xMS0wM1QxNjo0NToyOVrOszubRA==",
                    },
                    "nodes": [{"isResolved": True}, {"isResolved": True}],
                },
            },
        }
    }
}

PARENT_FOUND = {
    "data": {
        "repository": {
            "ref": {"name": "feat-taskflow-pr-board"},
            "pullRequests": {
                "nodes": [
                    {
                        "number": 49,
                        "state": "OPEN",
                        "headRepository": {"nameWithOwner": "EzeCuccorese/ia-spec-ops-engine"},
                    }
                ],
                "pageInfo": {"hasNextPage": False},
            },
        }
    }
}

PARENT_NO_BRANCH = {
    "data": {
        "repository": {
            "ref": None,
            "pullRequests": {"nodes": [], "pageInfo": {"hasNextPage": False}},
        }
    }
}

PR_NOT_FOUND = {
    "data": {"repository": {"defaultBranchRef": {"name": "main"}, "pullRequest": None}},
    "errors": [
        {
            "type": "NOT_FOUND",
            "path": ["repository", "pullRequest"],
            "locations": [{"line": 4, "column": 5}],
            "message": "Could not resolve to a PullRequest with the number of 99999.",
        }
    ],
}

REPO_NOT_FOUND = {
    "data": {"repository": None},
    "errors": [
        {
            "type": "NOT_FOUND",
            "path": ["repository"],
            "locations": [{"line": 1, "column": 9}],
            "message": "Could not resolve to a Repository with the name 'EzeCuccorese/nope-no-such-repo-zz'.",
        }
    ],
}

AUTH_STATUS_JSON = {
    "hosts": {
        "github.com": [
            {
                "state": "success",
                "active": True,
                "host": "github.com",
                "login": "EzeNube",
                "tokenSource": "keyring",
                "scopes": "admin:public_key, gist, read:org, repo",
                "gitProtocol": "ssh",
            },
            {
                "state": "success",
                "active": False,
                "host": "github.com",
                "login": "EzeCuccorese",
                "tokenSource": "keyring",
                "scopes": "admin:public_key, gist, read:org, repo",
                "gitProtocol": "ssh",
            },
        ]
    }
}
