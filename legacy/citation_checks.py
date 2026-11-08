"""Separate explicit source locations from numeric behavior claims.

Reading line 14 does not prove a limit of 14. Conversely, a correct citation
to line 14 should not require the source code to contain the number 14.
"""
import re


LOCATION = re.compile(
    r'(?P<file>[\w./-]+\.\w+):(?P<path_start>\d+)(?:[-–](?P<path_end>\d+))?(?!\w)'
    r'|\b(?:satır|line)\s+(?P<label_start>\d+)(?:\s*[-–]\s*(?P<label_end>\d+))?'
    r'|\b(?P<ordinal>\d+)\.\s*satır\w*', re.IGNORECASE)


def without_verified_locations(answer, citations):
    """Mask only verified location spans; return an issue for invented locations."""
    issues = []

    def replace(match):
        groups = match.groupdict()
        start = int(groups['path_start'] or groups['label_start'] or groups['ordinal'])
        end = int(groups['path_end'] or groups['label_end'] or start)
        file = groups['file']
        covered = any((file is None or item['file'] == file)
                      and item['start_line'] <= start <= end <= item['end_line']
                      for item in citations)
        if not covered:
            issues.append('Satır konumu bağlı kanıt aralığında değil: ' + match.group(0))
        # Invalid locations are reported explicitly, not repaired as code values.
        return ' [kaynak konumu] '

    return LOCATION.sub(replace, answer), issues
