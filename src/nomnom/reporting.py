"""Accessible outcome descriptions derived from engine results, not UI guesses."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Summary:
    title: str
    text: str
    notification: str


def summarize(result):
    if result.cancelled:
        title = 'Transfer cancelled'
    elif result.complete and not result.failures:
        title = 'Transfer complete'
    elif result.session_id:
        title = 'Backup finished — incomplete'
    elif result.verified:
        title = 'Transfer finished — with notes'
    else:
        title = 'Transfer failed'
    counts = ('Copied: {0}\nVerified: {1}\nAlready present: {2}\nSkipped: {3} (excluded by your file-selection settings)\n'
              'Failed entries/issues: {4}\nNot processed: {5}').format(
                  result.copied, result.verified, result.duplicates, result.skipped,
                  len(result.failures), result.not_processed)
    text = counts + '\nDestination: ' + result.destination
    if title == 'Transfer finished — with notes':
        text = 'The transfer is finished. Review the notes below.\n\n' + text
    elif title == 'Backup finished — incomplete':
        text = 'The backup attempt is finished, but some entries could not be backed up.\n\n' + text
    if result.failures:
        text += '\n\nDetails:\n' + '\n'.join(path + ': ' + error for path, error in result.failures)
    return Summary(title, text, counts.replace('\n', ' • ') + '\n' + result.destination)


def interrupted_summary(destination, error):
    # Unexpected exceptions may follow completed copies. Never invent zero counts.
    return Summary('Transfer stopped — outcome unavailable',
                   'Copied / verified / already present / skipped: unavailable\n'
                   'Final counts could not be recovered.\nDestination: ' + str(destination) + '\n\n' + str(error),
                   'Transfer stopped. Open Last transfer summary for details.')
