#!/usr/bin/python2.4
# -*- coding: utf-8 -*-
#  Copyright (C) 2007 Jacek Śliwerski (rzyjontko)
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; version 2.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.  

from translate.storage import factory
from phrase import Phrase
from pysqlite2 import dbapi2 as sqlite

import dircache, sys, os


def log(text, nonline=False):
    if nonline:
        print text,
    else:
        print text
    sys.stdout.flush()


def get_subdirs(dir):
    for r, dirs, files in os.walk(dir):
        if '.svn' in dirs:
            dirs.remove('.svn')
        return dirs


class Importer(object):
    def __init__(self, conn, parser_class):
        self.conn = conn
        self.parser_class = parser_class
    

    def store_words(self, phraseid, words):
        cnt = 1
        last = words[0]
        for word in words[1:]:
            if word == last:
                cnt += 1
            else:
                self.cursor.execute(u"insert into words(word, phraseid, count) values (?, ?, ?)", \
                                    (last, phraseid, cnt))
                last = word
                cnt = 1
        self.cursor.execute(u"insert into words(word, phraseid, count) values (?, ?, ?)", \
                            (last, phraseid, cnt))
                

    def store_phrase(self, pid, lid, sentence, lang):
        phrase = Phrase(sentence, lang[:2])
        length = phrase.length()
        if length == 0:
            return
        self.cursor.execute(u"insert into phrases(projectid, locationid, lang, length, phrase) values (?, ?, ?, ?, ?)", \
                            (pid, lid, lang, length, sentence))
        self.cursor.execute("select max(rowid) from phrases")
        phraseid = self.cursor.fetchone()[0]
        self.store_words(phraseid, phrase.canonical_list())


    def store_phrases(self, project, phrases):
        self.cursor.execute(u"insert into projects (path) values (?)", (project,))
        self.cursor.execute("select max (rowid) from projects")
        pid = self.cursor.fetchone()[0]
        lid = 0
        for source, ls in phrases.iteritems():
            if len(source) < 2:
                continue
            lid += 1
            self.store_phrase(pid, lid, source, "en")
            for lang, target in ls.iteritems():
                self.store_phrase(pid, lid, target, lang)


    def load_file(self, phrases, fname, lang):
        fname = fname.replace('/fr/', '/' + lang + '/', 1)
        store = self.parser_class.parsefile(fname)
        mlang = lang.replace('@', '_').lower()
        for unit in store.units:
            src = unit.source.encode('utf-8')
            dst = unit.target.encode('utf-8')
            if len(src) > 0:
                l = phrases.setdefault(src, {})
                l[mlang] = dst
        return len(store.units)


    def store_file(self, project, fname):
        phrases = {}
        for lang in self.langs:
            log("  + %s..." % lang, True)
            try:
                cnt = self.load_file(phrases, fname, lang)
                log("ok (%d)" % cnt)
            except:
                log("failed.")
        log("  phrases: %d" % len(phrases))
        self.store_phrases(project, phrases)
        

    def run(self, dir):
        #self.langs = ["pl", 'de']
        self.langs = get_subdirs(dir)
        for root, dirs, files in os.walk(os.path.join(dir, 'fr')):
            for f in files:
                if self.is_resource(f):
                    log("Importing %s..." % f)
                    self.cursor = self.conn.cursor()
                    self.store_file(self.project_name(f, root), os.path.join(root, f))
            if '.svn' in dirs:
                dirs.remove('.svn')


    def load_project_file(self, phrases, project, project_file):
        store = self.parser_class.parsefile(project_file)
        lang = project[:-3].replace('@', '_').lower()
        for unit in store.units:
            src = unit.source.encode('utf-8')
            dst = unit.target.encode('utf-8')
            if len(src) > 0:
                l = phrases.setdefault(src, {})
                l[lang] = dst
        return len(store.units)


    def run_projects(self, dir):
        #for proj in ['gtop']:
        for proj in get_subdirs(dir):
            log("Importing %s..." % proj)
            self.cursor = self.conn.cursor()
            phrases = {}
            proj_file_name = os.path.join(dir, proj)
            #for lang in ["pl.po", "de.po"]:
            for lang in os.listdir(proj_file_name):
                if not self.is_resource(lang):
                    continue
                log("  + %s..." % lang, True)
                try:
                    cnt = self.load_project_file(phrases, lang, os.path.join(proj_file_name, lang))
                    log("ok (%d)" % cnt)
                except:
                    log("failed.")
            log("  phrases: %d" % len(phrases))
            self.store_phrases(self.project_name(os.path.join(proj_file_name, lang)), phrases)


class KDE_Importer(Importer):
    def project_name(self, fname, root):
        return "K" + os.path.join(root[self.pathlen:], fname)
    
    def is_resource(self, fname):
        return fname.endswith('.po')
    
    def run(self, path):
        self.pathlen = len(path) + 3
        Importer.run(self, path)



class Mozilla_Importer(Importer):
    def project_name(self, fname, root):
        return "M" + os.path.join(root[self.pathlen:], fname)
    
    def is_resource(self, fname):
        return fname.endswith('.dtd.po') or fname.endswith('.properties.po')
    
    def run(self, path):
        self.pathlen = len(path) + 3
        Importer.run(self, path)


class Gnome_Importer(Importer):
    def project_name(self, filename):
        return "G" + filename[self.pathlen:]
    
    def is_resource(self, fname):
        return fname.endswith('.po') and not fname.startswith('en')
    
    def run(self, path):
        self.pathlen = len(path)
        Importer.run_projects(self, path)


cls = factory.getclass("kde.po")
conn = sqlite.connect('../data/eigth-i.db')
cursor = conn.cursor()
log("Dropping index...", True)
cursor.execute("drop index if exists loc_lang_idx")
cursor.execute("drop index if exists word_idx")
log("done.")

ki = KDE_Importer(conn, cls)
ki.run('/home/sliwers/kde-l10n')
mi = Mozilla_Importer(conn, cls)
mi.run('/home/sliwers/mozilla-po')
gi = Gnome_Importer(conn, cls)
gi.run('/home/sliwers/gnome-po')

log("Creating index...", True)
cursor.execute("create index loc_lang_idx on phrases (projectid, locationid, lang)")
cursor.execute("create index word_idx on words(word)")
log("done.")
conn.close()