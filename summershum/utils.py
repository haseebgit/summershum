import hashlib
import os
import shutil
import sys

import requests

from subprocess import Popen, PIPE

from model import Package, create_session

import logging
log = logging.getLogger("summershum")


# TODO -- get these from the fedmsg config loaded in consumer.py and cli.py
LOOKASIDE_URL = 'http://pkgs.fedoraproject.org/lookaside/pkgs/'
DB_URL = 'sqlite:////var/tmp/summershum.sqlite'


def download_lookaside(message):
    """ For a provided pkg updated, download the sources. """

    url = '%(base_url)s/%(pkg_name)s/%(sources)s/%(md5)s/%(sources)s' %(
        {
            'base_url': LOOKASIDE_URL, 'pkg_name': message['name'],
            'sources': message['filename'], 'md5': message['md5sum']
        }
    )

    local_filename = message['filename']

    req = requests.get(url, stream=True)
    with open(local_filename, 'wb') as stream:
        for chunk in req.iter_content(chunk_size=1024):
            if chunk:
                stream.write(chunk)
                stream.flush()


def get_sha1sum(session, message):
    """ Extract the content of the file extracted from the fedmsg message
    and browse the sources of the specified package and for each of the
    files in the sources get their sha1sum.
    """
    if not os.path.exists(message['filename']):
        raise IOError('File %s not found' % message['filename'])

    # FIXME: support gems
    if message['filename'].endswith('.gem'):
        return

    cmd = ['rpmdev-extract', message['filename']]
    proc = Popen(cmd, stdout=PIPE, stderr=PIPE)
    if proc.returncode:
        raise IOError(
            'Something went wrong when extracting %s' % message['filename'])

    filename = proc.communicate()[0].split('\n')[0].split('/')[0]

    index = message['filename'].rfind('-', 0, message['filename'].index('.'))
    version = message['filename'][(index + 1):]
    if version.endswith('.tar.gz') or version.endswith('.tar.xz'):
        version = version.rsplit('.', 2)[0]
    else:
        version = version.rsplit('.', 1)[0]

    count, stored = 0, 0
    for entry in walk_directory(filename):
        count = count + 1
        pkgobj = Package.exists(session, message['name'], entry[0], version)
        if not pkgobj:
            pkgobj = Package(
                pkg_name=message['name'],
                filename=entry[0],
                sha1sum=entry[1],
                version=version
            )
            session.add(pkgobj)
            stored = stored + 1
        else:
            pass
    session.commit()

    if filename and os.path.exists(filename):
        shutil.rmtree(filename)
        os.unlink(message['filename'])

    log.info("Stored %i of %i files" % (stored, count))


def walk_directory(directory):
    """ Return a tuple (filename, sha1) for every files present in the
    specified folder and do so recursively.
    """
    for root, dirnames, filenames in os.walk(directory):

        for filename in filenames:
            file_path = os.path.join(root, filename)
            with open(file_path) as stream:
                sha = hashlib.sha1(stream.read()).hexdigest()
                yield (file_path, sha)
