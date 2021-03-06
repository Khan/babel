# -*- coding: utf-8 -*-
"""
    babel.messages.extract
    ~~~~~~~~~~~~~~~~~~~~~~

    Basic infrastructure for extracting localizable messages from source files.

    This module defines an extensible system for collecting localizable message
    strings from a variety of sources. A native extractor for Python source
    files is builtin, extractors for other sources can be added using very
    simple plugins.

    The main entry points into the extraction functionality are the functions
    `extract_from_dir` and `extract_from_file`.

    :copyright: (c) 2013 by the Babel Team.
    :license: BSD, see LICENSE for more details.
"""

import os
import sys
from tokenize import generate_tokens, COMMENT, NAME, OP, STRING

from babel.util import parse_encoding, pathmatch, relpath
from babel._compat import PY2, text_type
from textwrap import dedent


GROUP_NAME = 'babel.extractors'

DEFAULT_KEYWORDS = {
    '_': None,
    'gettext': None,
    'ngettext': (1, 2),
    'ugettext': None,
    'ungettext': (1, 2),
    'dgettext': (2,),
    'dngettext': (2, 3),
    'N_': None,
    'pgettext': ((1, 'c'), 2)
}

DEFAULT_MAPPING = [('**.py', 'python')]

empty_msgid_warning = (
'%s: warning: Empty msgid.  It is reserved by GNU gettext: gettext("") '
'returns the header entry with meta information, not the empty string.')


def _strip_comment_tags(comments, tags):
    """Helper function for `extract` that strips comment tags from strings
    in a list of comment lines.  This functions operates in-place.
    """
    def _strip(line):
        for tag in tags:
            if line.startswith(tag):
                return line[len(tag):].strip()
        return line
    comments[:] = map(_strip, comments)


def parse_keywords(strings=[]):
    """Parse keywords specifications from the given list of strings.

    >>> kw = parse_keywords(['_', 'dgettext:2', 'dngettext:2,3',
        'pgettext:1c,2']).items()
    >>> kw.sort()
    >>> for keyword, indices in kw:
    ...     print (keyword, indices)
    ('_', None)
    ('dgettext', (2,))
    ('dngettext', (2, 3))
    ('pgettext', ((1, 'c'), 2))
    """
    keywords = {}
    for string in strings:
        if ':' in string:
            funcname, indices = string.split(':')
        else:
            funcname, indices = string, None
        if funcname not in keywords:
            if indices:
                inds = []
                for x in indices.split(','):
                    if x[-1] == 'c':
                        inds.append((int(x[:-1]), 'c'))
                    else:
                        inds.append(int(x))
                indices = tuple(inds)
            keywords[funcname] = indices
    return keywords


def extract_from_dir(dirname=None, method_map=DEFAULT_MAPPING,
                     options_map=None, keywords=DEFAULT_KEYWORDS,
                     comment_tags=(), callback=None, strip_comment_tags=False):
    """Extract messages from any source files found in the given directory.

    This function generates tuples of the form ``(filename, lineno, message,
    comments, context)``.

    Which extraction method is used per file is determined by the `method_map`
    parameter, which maps extended glob patterns to extraction method names.
    For example, the following is the default mapping:

    >>> method_map = [
    ...     ('**.py', 'python')
    ... ]

    This basically says that files with the filename extension ".py" at any
    level inside the directory should be processed by the "python" extraction
    method. Files that don't match any of the mapping patterns are ignored. See
    the documentation of the `pathmatch` function for details on the pattern
    syntax.

    The following extended mapping would also use the "genshi" extraction
    method on any file in "templates" subdirectory:

    >>> method_map = [
    ...     ('**/templates/**.*', 'genshi'),
    ...     ('**.py', 'python')
    ... ]

    The dictionary provided by the optional `options_map` parameter augments
    these mappings. It uses extended glob patterns as keys, and the values are
    dictionaries mapping options names to option values (both strings).

    The glob patterns of the `options_map` do not necessarily need to be the
    same as those used in the method mapping. For example, while all files in
    the ``templates`` folders in an application may be Genshi applications, the
    options for those files may differ based on extension:

    >>> options_map = {
    ...     '**/templates/**.txt': {
    ...         'template_class': 'genshi.template:TextTemplate',
    ...         'encoding': 'latin-1'
    ...     },
    ...     '**/templates/**.html': {
    ...         'include_attrs': ''
    ...     }
    ... }

    :param dirname: the path to the directory to extract messages from.  If
                    not given the current working directory is used.
    :param method_map: a list of ``(pattern, method)`` tuples that maps of
                       extraction method names to extended glob patterns
    :param options_map: a dictionary of additional options (optional)
    :param keywords: a dictionary mapping keywords (i.e. names of functions
                     that should be recognized as translation functions) to
                     tuples that specify which of their arguments contain
                     localizable strings
    :param comment_tags: a list of tags of translator comments to search for
                         and include in the results
    :param callback: a function that is called for every file that message are
                     extracted from, just before the extraction itself is
                     performed; the function is passed the filename, the name
                     of the extraction method and and the options dictionary as
                     positional arguments, in that order
    :param strip_comment_tags: a flag that if set to `True` causes all comment
                               tags to be removed from the collected comments.
    :see: `pathmatch`
    """
    if dirname is None:
        dirname = os.getcwd()
    if options_map is None:
        options_map = {}

    absname = os.path.abspath(dirname)
    for root, dirnames, filenames in os.walk(absname):
        for subdir in dirnames:
            if subdir.startswith('.') or subdir.startswith('_'):
                dirnames.remove(subdir)
        dirnames.sort()
        filenames.sort()

        # NOTE(csilvers): added for Khan Academy.
        # Check if entire directories are marked ignore, and skip if
        # so.  Due to how complex pattern-matching can be, we only
        # process method-map up until the first non-ignore directive:
        # we don't want to guess how an 'ignore' for a directory
        # interacts with a previous non-ignore directive!
        for i in xrange(len(dirnames) - 1, -1, -1):  # backwards eases deletion
            this_dirname = relpath(
                os.path.join(root, dirnames[i]).replace(os.sep, '/'),
                dirname
            )
            for pattern, method in method_map:
                if method != 'ignore':
                    break
                if (os.path.basename(pattern) == '**'
                    and pathmatch(os.path.dirname(pattern), this_dirname)):
                    del dirnames[i]
                    break

        for filename in filenames:
            filename = relpath(
                os.path.join(root, filename).replace(os.sep, '/'),
                dirname
            )
            for pattern, method in method_map:
                if pathmatch(pattern, filename):
                    filepath = os.path.join(absname, filename)
                    options = {}
                    for opattern, odict in options_map.items():
                        if pathmatch(opattern, filename):
                            options = odict
                    if callback:
                        callback(filename, method, options)
                    for lineno, message, comments, context in \
                          extract_from_file(method, filepath,
                                        keywords=keywords,
                                        comment_tags=comment_tags,
                                        options=options,
                                        strip_comment_tags=strip_comment_tags):
                        yield filename, lineno, message, comments, context
                    break


def extract_from_file(method, filename, keywords=DEFAULT_KEYWORDS,
                      comment_tags=(), options=None, strip_comment_tags=False):
    """Extract messages from a specific file.

    This function returns a list of tuples of the form ``(lineno, funcname,
    message)``.

    :param filename: the path to the file to extract messages from
    :param method: a string specifying the extraction method (.e.g. "python")
    :param keywords: a dictionary mapping keywords (i.e. names of functions
                     that should be recognized as translation functions) to
                     tuples that specify which of their arguments contain
                     localizable strings
    :param comment_tags: a list of translator tags to search for and include
                         in the results
    :param strip_comment_tags: a flag that if set to `True` causes all comment
                               tags to be removed from the collected comments.
    :param options: a dictionary of additional options (optional)
    """
    fileobj = open(filename, 'rb')
    try:
        return list(extract(method, fileobj, keywords, comment_tags, options,
                            strip_comment_tags))
    finally:
        fileobj.close()


def extract(method, fileobj, keywords=DEFAULT_KEYWORDS, comment_tags=(),
            options=None, strip_comment_tags=False):
    """Extract messages from the given file-like object using the specified
    extraction method.

    This function returns tuples of the form ``(lineno, message, comments)``.

    The implementation dispatches the actual extraction to plugins, based on
    the value of the ``method`` parameter.

    >>> source = '''# foo module
    ... def run(argv):
    ...    print _('Hello, world!')
    ... '''

    >>> from StringIO import StringIO
    >>> for message in extract('python', StringIO(source)):
    ...     print message
    (3, u'Hello, world!', [], None)

    :param method: a string specifying the extraction method (.e.g. "python");
                   if this is a simple name, the extraction function will be
                   looked up by entry point; if it is an explicit reference
                   to a function (of the form ``package.module:funcname`` or
                   ``package.module.funcname``), the corresponding function
                   will be imported and used
    :param fileobj: the file-like object the messages should be extracted from
    :param keywords: a dictionary mapping keywords (i.e. names of functions
                     that should be recognized as translation functions) to
                     tuples that specify which of their arguments contain
                     localizable strings
    :param comment_tags: a list of translator tags to search for and include
                         in the results
    :param options: a dictionary of additional options (optional)
    :param strip_comment_tags: a flag that if set to `True` causes all comment
                               tags to be removed from the collected comments.
    :raise ValueError: if the extraction method is not registered
    """
    func = None
    if ':' in method or '.' in method:
        if ':' not in method:
            lastdot = method.rfind('.')
            module, attrname = method[:lastdot], method[lastdot + 1:]
        else:
            module, attrname = method.split(':', 1)
        func = getattr(__import__(module, {}, {}, [attrname]), attrname)
    else:
        try:
            from pkg_resources import working_set
        except ImportError:
            pass
        else:
            for entry_point in working_set.iter_entry_points(GROUP_NAME,
                                                             method):
                func = entry_point.load(require=True)
                break
        if func is None:
            # if pkg_resources is not available or no usable egg-info was found
            # (see #230), we resort to looking up the builtin extractors
            # directly
            builtin = {
                'ignore': extract_nothing,
                'python': extract_python,
                'javascript': extract_javascript
            }
            func = builtin.get(method)
    if func is None:
        raise ValueError('Unknown extraction method %r' % method)

    options = options or {}
    # KA addition: The -k option ('-k = foo:1 bar baz:2c') is
    # equivalent to having passed -k 'something' on the commandline,
    # but just for this one file-type.  Likewise with -c ('-c =
    # NOTE:').  You can only add one comment-tag in this way, but as
    # many keywords as you want (we assume keywords don't have spaces
    # in them, so spaces separate unique -k entries).
    if '-k' in options:
        keywords = keywords.copy()
        keywords.update(parse_keywords(options['-k'].split(' ')))
    if '-c' in options:
        comment_tags = tuple(list(comment_tags) + [options['-c']])

    results = func(fileobj, keywords.keys(), comment_tags, options=options)

    for lineno, funcname, messages, comments in results:
        if funcname:
            spec = keywords[funcname] or (1,)
        else:
            spec = (1,)
        if not isinstance(messages, (list, tuple)):
            messages = [messages]
        if not messages:
            continue

        # Validate the messages against the keyword's specification
        context = None
        msgs = []
        invalid = False
        # last_index is 1 based like the keyword spec
        last_index = len(messages)
        for index in spec:
            if isinstance(index, tuple):
                context = messages[index[0] - 1]
                continue
            if last_index < index:
                # Not enough arguments
                invalid = True
                break
            message = messages[index - 1]
            if message is None:
                invalid = True
                break
            msgs.append(message)
        if invalid:
            continue

        # keyword spec indexes are 1 based, therefore '-1'
        if isinstance(spec[0], tuple):
            # context-aware *gettext method
            first_msg_index = spec[1] - 1
        else:
            first_msg_index = spec[0] - 1
        if not messages[first_msg_index]:
            # An empty string msgid isn't valid, emit a warning
            where = '%s:%i' % (hasattr(fileobj, 'name') and \
                                   fileobj.name or '(unknown)', lineno)
            sys.stderr.write((empty_msgid_warning % where) + '\n')
            continue

        messages = tuple(msgs)
        if len(messages) == 1:
            messages = messages[0]

        if strip_comment_tags:
            _strip_comment_tags(comments, comment_tags)
        yield lineno, messages, comments, context


def extract_nothing(fileobj, keywords, comment_tags, options):
    """Pseudo extractor that does not actually extract anything, but simply
    returns an empty list.
    """
    return []


def extract_python(fileobj, keywords, comment_tags, options):
    """Extract messages from Python source code.

    It returns an iterator yielding tuples in the following form ``(lineno,
    funcname, message, comments)``.

    :param fileobj: the seekable, file-like object the messages should be
                    extracted from
    :param keywords: a list of keywords (i.e. function names) that should be
                     recognized as translation functions
    :param comment_tags: a list of translator tags to search for and include
                         in the results
    :param options: a dictionary of additional options (optional)
    :rtype: ``iterator``
    """
    funcname = lineno = message_lineno = None
    call_stack = -1
    buf = []
    messages = []
    translator_comments = []
    in_def = in_translator_comments = False
    comment_tag = None

    encoding = parse_encoding(fileobj) or options.get('encoding', 'iso-8859-1')

    if PY2:
        next_line = fileobj.readline
    else:
        next_line = lambda: fileobj.readline().decode(encoding)

    tokens = generate_tokens(next_line)
    for tok, value, (lineno, _), _, _ in tokens:
        if call_stack == -1 and tok == NAME and value in ('def', 'class'):
            in_def = True
        elif tok == OP and value == '(':
            if in_def:
                # Avoid false positives for declarations such as:
                # def gettext(arg='message'):
                in_def = False
                continue
            if funcname:
                message_lineno = lineno
                call_stack += 1
        elif in_def and tok == OP and value == ':':
            # End of a class definition without parens
            in_def = False
            continue
        elif call_stack == -1 and tok == COMMENT:
            # Strip the comment token from the line
            if PY2:
                value = value.decode(encoding)
            value = value[1:].strip()
            # If execution reaches this point, let's see if comment line
            # starts with one of the comment tags
            for comment_tag in comment_tags:
                if value.startswith(comment_tag):
                    in_translator_comments = True
                    translator_comments.append((lineno, value))
                    break

            if in_translator_comments and \
                    translator_comments[-1][0] == lineno - 1:
                # We're already inside a translator comment, continue appending
                # to previous comment
                previous_comment_value = translator_comments[-1][1]
                translator_comments[-1] = (lineno, "%s %s" % (
                    previous_comment_value, value))
                continue

        elif funcname and tok == OP and value == '[':     # dict lookup
            call_stack += 1
        elif funcname and call_stack == 0:
            if tok == OP and value == ')':
                if buf:
                    messages.append(''.join(buf))
                    del buf[:]
                else:
                    messages.append(None)

                if len(messages) > 1:
                    messages = tuple(messages)
                else:
                    messages = messages[0]
                # Comments don't apply unless they immediately preceed the
                # message
                if translator_comments and \
                        translator_comments[-1][0] < message_lineno - 1:
                    translator_comments = []

                yield (message_lineno, funcname, messages,
                       [comment[1] for comment in translator_comments])

                funcname = lineno = message_lineno = None
                call_stack = -1
                messages = []
                translator_comments = []
                in_translator_comments = False
            elif tok == STRING:
                # Unwrap quotes in a safe manner, maintaining the string's
                # encoding
                # https://sourceforge.net/tracker/?func=detail&atid=355470&
                # aid=617979&group_id=5470
                value = eval('# coding=%s\n%s' % (str(encoding), value),
                             {'__builtins__': {}}, {})
                if PY2 and not isinstance(value, text_type):
                    value = value.decode(encoding)
                buf.append(value)
            elif tok == OP and value == ',':
                if buf:
                    messages.append(''.join(buf))
                    del buf[:]
                else:
                    messages.append(None)
                if translator_comments:
                    # We have translator comments, and since we're on a
                    # comma(,) user is allowed to break into a new line
                    # Let's increase the last comment's lineno in order
                    # for the comment to still be a valid one
                    old_lineno, old_comment = translator_comments.pop()
                    translator_comments.append((old_lineno + 1, old_comment))
        elif call_stack > 0 and tok == OP and value in [')', ']']:
            call_stack -= 1
        elif funcname and call_stack == -1:
            funcname = None
        elif tok == NAME and value in keywords:
            funcname = value


def extract_javascript(fileobj, keywords, comment_tags, options):
    """Extract messages from JavaScript source code.

    :param fileobj: the seekable, file-like object the messages should be
                    extracted from
    :param keywords: a list of keywords (i.e. function names) that should be
                     recognized as translation functions
    :param comment_tags: a list of translator tags to search for and include
                         in the results
    :param options: a dictionary of additional options (optional)
                    set the option of 'messages_only' to True and this method
                    will yield a tuple of messages and their file position

    If 'messages_only' is set to True then the return type is a tuple holding
    ``(messages, start, end)``. This represents a list of message strings and
    two number positions of those strings in the file. The positions in the
    file are absolute positions of the text in the file. For example:

        $._("Hello.")
            ^......^ - Message position

    Will yield: ``(["Hello."], 4, 11)``. And for pluralization:

        $.ngettext("Singular %s.", "Plural %s.", num)
                   ^..........................^ - Message position

    Will yield: ``(["Singular %s.", "Plural %s."], 12, 39)``. Note that the
    position of the start and end even transcend the comma and whitespace
    inbetween the two strings. This even works for more complicated examples:

              v.............
        $._(  "Hello %s " +
            "How are you doing?"  , name);
        .......................^ - Message position.

    This will yield: ``(["Hello %s How are you doing?"], 6, 43)``.

    All of this makes it easy to replace those string messages with new
    messages since you can quickly replace all of the text between the start
    and end positions with your modified text.
    """
    from babel.messages.jslexer import tokenize, unquote_string
    funcname = message_lineno = None
    messages = []
    last_argument = None
    translator_comments = []
    concatenate_next = False
    encoding = options.get('encoding', 'utf-8')
    last_token = None
    call_stack = -1

    # NOTE(djf): function invocations never follow these JavaScript keywords
    DECLARATION_KEYWORDS = {"function", "class", "var", "let", "const"}

    # NOTE(jeresig): Custom functionality added.
    # setting the option of 'messages_only' to True and this method
    # will yield a tuple of messages and their file position
    messages_only = options.get('messages_only', False)

    if messages_only:
        messages_start = messages_end = None

    for token in tokenize(fileobj.read().decode(encoding)):
        # NOTE(jeresig): Made it so that ( or [ or { all increase
        # the call stack (to avoid capturing things contained within
        # these particular constructs).
        # NOTE(djf): But only increment callstack from -1 to 0 on open paren
        # Otherwise `_[` looks like a function call instead of array access.
        if token.type == 'operator' and token.value in ('{', '[', '('):
            if funcname and (token.value == '(' or call_stack >= 0):
                message_lineno = token.lineno
                call_stack += 1

        elif call_stack == -1 and token.type == 'linecomment':
            value = token.value[2:].strip()

            for comment_tag in comment_tags:
                if value.startswith(comment_tag):
                    translator_comments.append((token.lineno, value.strip()))
                    break

            if translator_comments and \
               translator_comments[-1][0] == token.lineno - 1:
                # Add this comment to the one on the previous row
                translator_comments[-1] = (token.lineno, "%s %s" % (
                    translator_comments[-1][1], value))
                continue

        elif token.type == 'multilinecomment':
            # only one multi-line comment may preceed a translation
            translator_comments = []
            value = token.value[2:-2].strip()
            for comment_tag in comment_tags:
                if value.startswith(comment_tag):
                    lines = value.splitlines()
                    if lines:
                        lines[0] = lines[0].strip()
                        lines[1:] = dedent('\n'.join(lines[1:])).splitlines()
                        translator_comments.append(
                            (token.lineno+len(lines), ' '.join(lines)))
                    break


        elif funcname and call_stack == 0:
            if token.type == 'operator' and token.value == ')':
                if last_argument is not None:
                    # NOTE(jeresig): Custom functionality added.
                    if messages_only:
                        # End position is continually updated after every
                        # message (making it so that the end of the last
                        # message is the last reported end position)
                        messages_end = token.match.start()
                    messages.append(last_argument)
                if len(messages) > 1:
                    messages = tuple(messages)
                elif messages:
                    messages = messages[0]
                else:
                    messages = None

                # Comments don't apply unless they immediately precede the
                # message
                if translator_comments and \
                   translator_comments[-1][0] < message_lineno - 1:
                    translator_comments = []

                if messages is not None:
                    # NOTE(jeresig): Custom functionality added.
                    if messages_only:
                        yield (messages, messages_start, messages_end)
                        messages_start = messages_end = None
                    else:
                        yield (message_lineno, funcname, messages,
                           [comment[1] for comment in translator_comments])

                funcname = message_lineno = last_argument = None
                concatenate_next = False
                translator_comments = []
                messages = []
                call_stack = -1

            elif token.type == 'string':
                # NOTE(jeresig): Custom functionality added.
                # We've encountered a string, strings hold messages to be
                # translated. We use this opportunity to update the
                # messages_start and messages_end variables which keep track of
                # the positions of the messages in the file.
                if messages_only and messages_start is None:
                    # Only update the messages_start position when we're at the
                    # first message.
                    messages_start = token.match.start()

                new_value = unquote_string(token.value)
                if concatenate_next:
                    last_argument = (last_argument or '') + new_value
                    concatenate_next = False
                else:
                    last_argument = new_value

            elif token.type == 'operator':
                if token.value == ',':
                    if last_argument is not None:
                        # NOTE(jeresig): Custom functionality added.
                        if messages_only:
                            # End position is continually updated after every
                            # message (making it so that the end of the last
                            # message is the last reported end position)
                            messages_end = token.match.start()
                        messages.append(last_argument)
                        last_argument = None
                    else:
                        messages.append(None)
                    concatenate_next = False
                elif token.value == '+':
                    concatenate_next = True
        # NOTE(jeresig): Made it so that ) or ] or } all decrease
        # the call stack (to avoid capturing things contained within
        # these particular constructs).
        elif call_stack > 0 and token.type == 'operator' \
             and token.value in ('}', ']', ')'):
            call_stack -= 1

        elif funcname and call_stack == -1:
            funcname = None

        elif call_stack == -1 and token.type == 'name' and \
             token.value in keywords and \
             (last_token is None or last_token.type != 'name' or
              last_token.value not in DECLARATION_KEYWORDS):
            funcname = token.value

        last_token = token
