"""Check GitHub Actions workflow files for ${{ }} injection vulnerabilities.

Checks all run: blocks for direct ${{ }} expression interpolation,
which can lead to shell/code injection when values come from untrusted input
(repository_dispatch, pull_request, issue comments, etc.).

workflow_dispatch inputs are lower risk (requires repo write access)
but still flagged as warnings.
"""
import yaml
import sys
import glob

# Events where input is untrusted (external)
UNTRUSTED_EVENTS = {'repository_dispatch', 'pull_request', 'pull_request_target',
                     'issue_comment', 'issues', 'discussion', 'discussion_comment'}

errors = []
warnings = []

for filepath in glob.glob('.github/workflows/*.yml'):
    with open(filepath) as fh:
        wf = yaml.safe_load(fh)

    # Determine if workflow has untrusted triggers
    on_config = wf.get('on') or wf.get(True) or {}
    if isinstance(on_config, str):
        triggers = {on_config}
    elif isinstance(on_config, list):
        triggers = set(on_config)
    elif isinstance(on_config, dict):
        triggers = set(on_config.keys())
    else:
        triggers = set()

    has_untrusted = bool(triggers & UNTRUSTED_EVENTS)

    for job_name, job in (wf.get('jobs') or {}).items():
        for step in (job.get('steps') or []):
            run_block = step.get('run', '')
            if '${' + '{' in run_block:
                step_name = step.get('name', 'unnamed')
                for i, line in enumerate(run_block.split('\n'), 1):
                    if '${' + '{' in line:
                        msg = f'{filepath}: {job_name}/{step_name} L{i}: {line.strip()[:100]}'
                        if has_untrusted:
                            errors.append(msg)
                        else:
                            warnings.append(msg)

if warnings:
    print(f'⚠️  {len(warnings)} warning(s) — ${{{{ }}}} in run blocks (workflow_dispatch only):')
    for w in warnings:
        print(f'  ::warning::{w}')

if errors:
    print(f'\n❌ {len(errors)} error(s) — ${{{{ }}}} in run blocks with UNTRUSTED triggers:')
    for e in errors:
        print(f'  ::error::{e}')
    sys.exit(1)

if not errors:
    print('✅ No critical injection vulnerabilities found.')
