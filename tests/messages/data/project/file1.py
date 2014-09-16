# -*- coding: utf-8 -*-
# file1.py for tests

from gettext import gettext as _
def foo():
    # TRANSLATOR: This will be a translator comment,
    # that will merge several lines
    print _('bar')
