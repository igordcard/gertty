# Copyright 2014 OpenStack Foundation
# Copyright 2014 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import collections
import getpass
import os
import re
import sys
try:
    import ordereddict
except:
    pass
import yaml

from six.moves.urllib import parse as urlparse
import voluptuous as v

import gertty.commentlink
import gertty.palette
import gertty.keymap

try:
    OrderedDict = collections.OrderedDict
except AttributeError:
    OrderedDict = ordereddict.OrderedDict

DEFAULT_CONFIG_PATH='~/.gertty.yaml'

class ConfigSchema(object):
    server = {v.Required('name'): str,
              v.Required('url'): str,
              v.Required('username'): str,
              'password': str,
              'verify-ssl': bool,
              'ssl-ca-path': str,
              'dburi': str,
              v.Required('git-root'): str,
              'git-url': str,
              'log-file': str,
              'lock-file': str,
              'socket': str,
              'auth-type': v.Any('basic', 'digest', 'form'),
              }

    servers = [server]

    _sort_by = v.Any('number', 'updated', 'last-seen', 'project')
    sort_by = v.Any(_sort_by, [_sort_by])

    text_replacement = {'text': v.Any(str,
                                      {'color': str,
                                       v.Required('text'): str})}

    link_replacement = {'link': {v.Required('url'): str,
                                 v.Required('text'): str}}

    search_replacement = {'search': {v.Required('query'): str,
                                     v.Required('text'): str}}

    replacement = v.Any(text_replacement, link_replacement, search_replacement)

    palette = {v.Required('name'): str,
               v.Match('(?!name)'): [str]}

    palettes = [palette]

    commentlink = {v.Required('match'): str,
                   v.Required('replacements'): [replacement],
                   'test-result': str}

    commentlinks = [commentlink]

    dashboard = {v.Required('name'): str,
                 v.Required('query'): str,
                 v.Optional('sort-by'): sort_by,
                 v.Optional('reverse'): bool,
                 v.Required('key'): str}

    dashboards = [dashboard]

    reviewkey_approval = {v.Required('category'): str,
                          v.Required('value'): int}

    reviewkey = {v.Required('approvals'): [reviewkey_approval],
                 v.Optional('message'): str,
                 'submit': bool,
                 v.Required('key'): str}

    reviewkeys = [reviewkey]

    hide_comment = {v.Required('author'): str}

    hide_comments = [hide_comment]

    change_list_options = {'sort-by': sort_by,
                           'reverse': bool}

    keymap = {v.Required('name'): str,
              v.Match('(?!name)'): v.Any([[str], str], [str], str)}

    keymaps = [keymap]

    thresholds = [int, int, int, int, int, int, int, int]
    size_column = {v.Required('type'): v.Any('graph', 'split-graph', 'number',
                                             'disabled', None),
                   v.Optional('thresholds'): thresholds}

    def getSchema(self, data):
        schema = v.Schema({v.Required('servers'): self.servers,
                           'palettes': self.palettes,
                           'palette': str,
                           'keymaps': self.keymaps,
                           'keymap': str,
                           'commentlinks': self.commentlinks,
                           'dashboards': self.dashboards,
                           'reviewkeys': self.reviewkeys,
                           'change-list-query': str,
                           'diff-view': str,
                           'hide-comments': self.hide_comments,
                           'thread-changes': bool,
                           'display-times-in-utc': bool,
                           'handle-mouse': bool,
                           'breadcrumbs': bool,
                           'close-change-on-review': bool,
                           'change-list-options': self.change_list_options,
                           'expire-age': str,
                           'size-column': self.size_column,
                           })
        return schema

class Config(object):
    def __init__(self, server=None, palette='default', keymap='default',
                 path=DEFAULT_CONFIG_PATH):
        self.path = os.path.expanduser(path)

        if not os.path.exists(self.path):
            self.printSample()
            sys.exit(1)

        self.config = yaml.safe_load(open(self.path))
        schema = ConfigSchema().getSchema(self.config)
        schema(self.config)
        server = self.getServer(server)
        self.server = server
        url = server['url']
        if not url.endswith('/'):
            url += '/'
        self.url = url
        result = urlparse.urlparse(url)
        self.hostname = result.netloc
        self.username = server['username']
        self.password = server.get('password')
        if self.password is None:
            self.password = getpass.getpass("Password for %s (%s): "
                                            % (self.url, self.username))
        else:
            # Ensure file is only readable by user as password is stored in
            # file.
            mode = os.stat(self.path).st_mode & 0o0777
            if not mode == 0o600:
                print (
                    "Error: Config file '{}' contains a password and does "
                    "not have permissions set to 0600.\n"
                    "Permissions are: {}".format(self.path, oct(mode)))
                sys.exit(1)
        self.auth_type = server.get('auth-type', 'digest')
        self.verify_ssl = server.get('verify-ssl', True)
        if not self.verify_ssl:
            os.environ['GIT_SSL_NO_VERIFY']='true'
        self.ssl_ca_path = server.get('ssl-ca-path', None)
        if self.ssl_ca_path is not None:
            self.ssl_ca_path = os.path.expanduser(self.ssl_ca_path)
            # Gertty itself uses the Requests library
            os.environ['REQUESTS_CA_BUNDLE'] = self.ssl_ca_path
            # And this is to allow Git callouts
            os.environ['GIT_SSL_CAINFO'] = self.ssl_ca_path
        self.git_root = os.path.expanduser(server['git-root'])
        git_url = server.get('git-url', self.url + 'p/')
        if not git_url.endswith('/'):
            git_url += '/'
        self.git_url = git_url
        self.dburi = server.get('dburi',
                                'sqlite:///' + os.path.expanduser('~/.gertty.db'))
        socket_path = server.get('socket', '~/.gertty.sock')
        self.socket_path = os.path.expanduser(socket_path)
        log_file = server.get('log-file', '~/.gertty.log')
        self.log_file = os.path.expanduser(log_file)
        lock_file = server.get('lock-file', '~/.gertty.%s.lock' % server['name'])
        self.lock_file = os.path.expanduser(lock_file)

        self.palettes = {'default': gertty.palette.Palette({}),
                         'light': gertty.palette.Palette(gertty.palette.LIGHT_PALETTE),
                         }
        for p in self.config.get('palettes', []):
            if p['name'] not in self.palettes:
                self.palettes[p['name']] = gertty.palette.Palette(p)
            else:
                self.palettes[p['name']].update(p)
        self.palette = self.palettes[self.config.get('palette', palette)]

        self.keymaps = {'default': gertty.keymap.KeyMap({}),
                        'vi': gertty.keymap.KeyMap(gertty.keymap.VI_KEYMAP)}
        for p in self.config.get('keymaps', []):
            if p['name'] not in self.keymaps:
                self.keymaps[p['name']] = gertty.keymap.KeyMap(p)
            else:
                self.keymaps[p['name']].update(p)
        self.keymap = self.keymaps[self.config.get('keymap', keymap)]

        self.commentlinks = [gertty.commentlink.CommentLink(c)
                             for c in self.config.get('commentlinks', [])]
        self.commentlinks.append(
            gertty.commentlink.CommentLink(dict(
                    match="(?P<url>https?://\\S*)",
                    replacements=[
                        dict(link=dict(
                                text="{url}",
                                url="{url}"))])))

        self.project_change_list_query = self.config.get('change-list-query', 'status:open')

        self.diff_view = self.config.get('diff-view', 'side-by-side')

        self.dashboards = OrderedDict()
        for d in self.config.get('dashboards', []):
            self.dashboards[d['key']] = d
            self.dashboards[d['key']]

        self.reviewkeys = OrderedDict()
        for k in self.config.get('reviewkeys', []):
            self.reviewkeys[k['key']] = k

        self.hide_comments = []
        for h in self.config.get('hide-comments', []):
            self.hide_comments.append(re.compile(h['author']))

        self.thread_changes = self.config.get('thread-changes', True)
        self.utc = self.config.get('display-times-in-utc', False)
        self.breadcrumbs = self.config.get('breadcrumbs', True)
        self.close_change_on_review = self.config.get('close-change-on-review', False)
        self.handle_mouse = self.config.get('handle-mouse', True)

        change_list_options = self.config.get('change-list-options', {})
        self.change_list_options = {
            'sort-by': change_list_options.get('sort-by', 'number'),
            'reverse': change_list_options.get('reverse', False)}

        self.expire_age = self.config.get('expire-age', '2 months')

        self.size_column = self.config.get('size-column', {})
        self.size_column['type'] = self.size_column.get('type', 'graph')
        if self.size_column['type'] == 'graph':
            self.size_column['thresholds'] = self.size_column.get('thresholds',
                [1, 10, 100, 1000])
        else:
            self.size_column['thresholds'] = self.size_column.get('thresholds',
                [1, 10, 100, 200, 400, 600, 800, 1000])

    def getServer(self, name=None):
        for server in self.config['servers']:
            if name is None or name == server['name']:
                return server
        return None

    def printSample(self):
        filename = 'share/gertty/examples'
        print("""Gertty requires a configuration file at ~/.gertty.yaml
If the file contains a password then permissions must be set to 0600.

Several sample configuration files were installed with Gertty and are
available in %s in the root of the installation.

For more information, please see the README.
""" % (filename,))
