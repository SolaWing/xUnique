#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
This software is licensed under the Apache 2 license, quoted below.

Copyright 2014 Xiao Wang <wangxiao8611@gmail.com, http://fclef.wordpress.com/about>

Licensed under the Apache License, Version 2.0 (the "License"); you may not
use this file except in compliance with the License. You may obtain a copy of
the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations under
the License.
"""

from __future__ import unicode_literals
from __future__ import print_function
from subprocess import (check_output as sp_co, CalledProcessError)
from os import path, unlink, rename
from hashlib import md5 as hl_md5
from json import (loads as json_loads, dump as json_dump)
from fileinput import (input as fi_input, close as fi_close)
from re import compile as re_compile
from sys import (argv as sys_argv, getfilesystemencoding as sys_get_fs_encoding, version_info)
from filecmp import cmp as filecmp_cmp
from optparse import OptionParser


def construct_compatibility_layer():
    if version_info.major == 3:
        class SixPython3Impl(object):
            PY2 = False
            PY3 = True
            text_type = str
            string_types = (str,)

        return SixPython3Impl
    elif version_info.major == 2:
        class SixPython2Impl(object):
            PY2 = True
            PY3 = False
            text_type = unicode
            string_types = (basestring,)

        return SixPython2Impl
    else:
        raise XUniqueExit("unsupported python version")


six = construct_compatibility_layer()

md5_hex = lambda a_str: hl_md5(a_str.encode('utf-8')).hexdigest().upper()
if six.PY2:
    print_ng = lambda *args, **kwargs: print(*[six.text_type(i).encode(sys_get_fs_encoding()) for i in args], **kwargs)
    output_u8line = lambda *args: print(*[six.text_type(i).encode('utf-8') for i in args], end='')
elif six.PY3:
    print_ng = lambda *args, **kwargs: print(*args, **kwargs)
    output_u8line = lambda *args: print(*args, end='')


def decoded_string(string, encoding=None):
    if isinstance(string, six.text_type):
        return string
    return string.decode(encoding or sys_get_fs_encoding())


def warning_print(*args, **kwargs):
    new_args = list(args)
    new_args[0] = '\x1B[33m{}'.format(new_args[0])
    new_args[-1] = '{}\x1B[0m'.format(new_args[-1])
    print_ng(*new_args, **kwargs)


def success_print(*args, **kwargs):
    new_args = list(args)
    new_args[0] = '\x1B[32m{}'.format(new_args[0])
    new_args[-1] = '{}\x1B[0m'.format(new_args[-1])
    print_ng(*new_args, **kwargs)


class XUnique(object):
    def __init__(self, target_path, verbose=False):
        # check project path
        abs_target_path = path.abspath(target_path)
        if not path.exists(abs_target_path):
            raise XUniqueExit('Path "',abs_target_path ,'" not found!')
        elif abs_target_path.endswith('xcodeproj'):
            self.xcodeproj_path = abs_target_path
            self.xcode_pbxproj_path = path.join(abs_target_path, 'project.pbxproj')
        elif abs_target_path.endswith('project.pbxproj'):
            self.xcode_pbxproj_path = abs_target_path
            self.xcodeproj_path = path.dirname(self.xcode_pbxproj_path)
        else:
            raise XUniqueExit("Path must be dir '.xcodeproj' or file 'project.pbxproj'")
        self.verbose = verbose
        self.vprint = print if self.verbose else lambda *a, **k: None
        self.proj_root = self.get_proj_root()
        self.proj_json = self.pbxproj_to_json()
        self.nodes = self.proj_json['objects']
        self.root_hex = self.proj_json['rootObject']
        self.root_node = self.nodes[self.root_hex]
        self.main_group_hex = self.root_node['mainGroup']
        self.__result = {}
        root_new_hex = md5_hex(self.proj_root)
        self.__new_key_path_dict = {root_new_hex : self.proj_root}
        # initialize root content
        self.__result.update(
            {
                self.root_hex: {'path': self.proj_root,
                                'new_key': root_new_hex,
                                'type': self.root_node['isa']
                                }
            })
        self._is_modified = False

    @property
    def is_modified(self):
        return self._is_modified

    def pbxproj_to_json(self):
        pbproj_to_json_cmd = ['plutil', '-convert', 'json', '-o', '-', self.xcode_pbxproj_path]
        try:
            json_unicode_str = decoded_string(sp_co(pbproj_to_json_cmd))
            return json_loads(json_unicode_str)
        except CalledProcessError as cpe:
            raise XUniqueExit("""{}
Please check:
1. You have installed Xcode Command Line Tools and command 'plutil' could be found in $PATH;
2. The project file is not broken, such like merge conflicts, incomplete content due to xUnique failure. """.format(
                cpe.output))

    def __update_result(self, current_hex, path, new_key, atype):
        old = self.__result.get(current_hex)
        if old:
            self.vprint("override", current_hex)
            self.__new_key_path_dict.pop(old['new_key'], None)
        while new_key in self.__new_key_path_dict and self.__new_key_path_dict[new_key] != path:
            self.vprint("hash conflicts old:{} => new:{}".format(current_hex, new_key))
            new_key = md5_hex(new_key) # rehash to avoid conflicts of different path
        self.__new_key_path_dict[new_key] = path
        self.__result[current_hex] = {'path': path, 'new_key': new_key, 'type': atype}
        return new_key

    def __set_to_result(self, parent_hex, current_hex, current_path_key):
        current_node = self.nodes[current_hex]
        isa_type = current_node['isa']
        if isinstance(current_path_key, (list, tuple)):
            current_path = '/'.join([str(current_node[i]) for i in current_path_key])
        elif isinstance(current_path_key, six.string_types):
            if current_path_key in current_node.keys():
                current_path = current_node[current_path_key]
            else:
                current_path = current_path_key
        else:
            raise KeyError('current_path_key must be list/tuple/string')
        cur_abs_path = '{}/{}'.format(self.__result[parent_hex]['path'], current_path)
        new_key = md5_hex(cur_abs_path)
        return self.__update_result(current_hex, '{}[{}]'.format(isa_type, cur_abs_path), new_key, isa_type)

    def get_proj_root(self):
        """PBXProject name,the root node"""
        pbxproject_ptn = re_compile('(?<=PBXProject ").*(?=")')
        with open(self.xcode_pbxproj_path) as pbxproj_file:
            for line in pbxproj_file:
                # project.pbxproj is an utf-8 encoded file
                line = decoded_string(line, 'utf-8')
                result = pbxproject_ptn.search(line)
                if result:
                    # Backward compatibility using suffix
                    return '{}.xcodeproj'.format(result.group())
        # project file must be in ASCII format
        if 'Pods.xcodeproj' in self.xcode_pbxproj_path:
            raise XUniqueExit("Pods project file should be in ASCII format, but Cocoapods converted Pods project file to XML by default. Install 'xcproj' in your $PATH via brew to fix.")
        else:
            raise XUniqueExit("File 'project.pbxproj' is broken. Cannot find PBXProject name.")

    def subproject(self, abspath):
        if not hasattr(self, '_subproject'):
            self._subproject = {}
        sub_proj = self._subproject.get(abspath)
        if sub_proj is None:
            sub_proj = XUnique(abspath, self.verbose)
            self._subproject[abspath] = sub_proj
        return sub_proj

    def unique_project(self):
        """iterate all nodes in pbxproj file:

        PBXProject
        XCConfigurationList
        PBXNativeTarget
        PBXTargetDependency
        PBXContainerItemProxy
        XCBuildConfiguration
        PBX*BuildPhase
        PBXBuildFile
        PBXReferenceProxy
        PBXFileReference
        PBXGroup
        PBXVariantGroup
        """
        self.__unique_project(self.root_hex)
        if self.verbose:
            debug_result_file_path = path.join(self.xcodeproj_path, 'debug_result.json')
            with open(debug_result_file_path, 'w') as debug_result_file:
                json_dump(self.__result, debug_result_file)
            warning_print("Debug result json file has been written to '", debug_result_file_path, sep='')
        self.substitute_old_keys()

    def substitute_old_keys(self):
        self.vprint('replace UUIDs and remove unused UUIDs')
        key_ptn = re_compile('(?<=\s)([0-9A-Z]{24}|[0-9A-F]{32})(?=[\s;])')
        removed_lines = []
        for line in fi_input(self.xcode_pbxproj_path, backup='.ubak', inplace=1):
            # project.pbxproj is an utf-8 encoded file
            line = decoded_string(line, 'utf-8')
            key_list = key_ptn.findall(line)
            if not key_list:
                output_u8line(line)
            else:
                new_line = line
                # remove line with non-existing element
                if self.__result.get('to_be_removed') and any(
                        i for i in key_list if i in self.__result['to_be_removed']):
                    removed_lines.append(new_line)
                    continue
                # remove incorrect entry that somehow does not exist in project node tree
                elif not all(self.__result.get(uuid) for uuid in key_list):
                    removed_lines.append(new_line)
                    continue
                else:
                    for key in key_list:
                        new_key = self.__result[key]['new_key']
                        new_line = new_line.replace(key, new_key)
                    output_u8line(new_line)
        fi_close()
        tmp_path = self.xcode_pbxproj_path + '.ubak'
        if filecmp_cmp(self.xcode_pbxproj_path, tmp_path, shallow=False):
            unlink(self.xcode_pbxproj_path)
            rename(tmp_path, self.xcode_pbxproj_path)
            warning_print('Ignore uniquify, no changes made to "', self.xcode_pbxproj_path, sep='')
        else:
            unlink(tmp_path)
            self._is_modified = True
            success_print('Uniquify done')
            if self.__result.get('uniquify_warning'):
                warning_print(*self.__result['uniquify_warning'])
            if removed_lines:
                warning_print('Following lines were deleted because of invalid format or no longer being used:')
                print_ng(*removed_lines, end='')

    def sort_pbxproj(self, sort_pbx_by_file_name=False):
        self.vprint('sort project.xpbproj file')
        removed_lines = []

        files_start_ptn = re_compile('^(\s*)files = \(\s*$')
        files_key_ptn = re_compile('((?<=[A-Z0-9]{24} \/\* )|(?<=[A-F0-9]{32} \/\* )).+?(?= in )')
        children_start_ptn = re_compile('^(\s*)children = \(\s*$')
        children_pbx_key_ptn = re_compile('((?<=[A-Z0-9]{24} \/\* )|(?<=[A-F0-9]{32} \/\* )).+?(?= \*\/)')
        array_end_ptn = '^{space}\);\s*$'

        pbx_section_start_ptn = re_compile('^\s*\/\*\s*Begin (.+) section.*$')
        pbx_section_end_ptn =  '^\s*\/\*\s*End {name} section.*$'
        pbx_section_names = {
            'PBXGroup',
            'PBXFileReference',
            'PBXBuildFile',
            'PBXContainerItemProxy',
            'PBXReferenceProxy',
            'PBXNativeTarget',
            'PBXTargetDependency',
            'PBXSourcesBuildPhase',
            'PBXFrameworksBuildPhase',
            'PBXResourcesBuildPhase',
            'PBXCopyFilesBuildPhase',
            'PBXShellScriptBuildPhase',
            'XCBuildConfiguration',
            'XCConfigurationList',
            'XCVersionGroup',
            'PBXVariantGroup',
            'PBXProject',
        }
        pbx_section_names_sort_by_name = {'PBXFileReference', 'PBXBuildFile'} if sort_pbx_by_file_name else set()
        pbx_section_item_ptn = re_compile(r'^(\s*){hex_group}\s+{name_group}\s*=\s*\{{{oneline_end_group}\s*$'.format(
            hex_group = '((?:[A-Z0-9]{24})|(?:[A-F0-9]{32}))',
            name_group = r'(?:\/\* (.+?) \*\/)?',
            oneline_end_group = '(?:.+(};))?'
        ))
        pbx_section_item_end_ptn = r"^{space}\}};\s*$"

        empty_line_ptn = re_compile('^\s*$')
        children_nosort_group = set()
        try:
            # projectReferences may order by xcode, don't sort it
            def get_hex(old_hex):
                if old_hex in self.__result: return self.__result[old_hex]['new_key']
                return old_hex
            for pr in self.root_node['projectReferences']:
                children_nosort_group.add(get_hex(pr['ProductGroup']))
        except KeyError as e: pass

        def file_dir_order(x):
            x = children_pbx_key_ptn.search(x).group()
            return '.' in x, x

        output_stack = [output_u8line]
        write = lambda *args: output_stack[-1](*args)

        deal_stack = []
        deal = lambda line: deal_stack[-1](line)

        def check_section(line):
            section_match = pbx_section_start_ptn.search(line)
            if section_match:
                write(line)
                section_name = section_match.group(1)
                if section_name in pbx_section_names:
                    section_items = []
                    end_ptn = re_compile(pbx_section_end_ptn.format(name=section_name))
                    def check_end(line):
                        end_match = bool(end_ptn.search(line))
                        if end_match:
                            if section_items:
                                section_items.sort(key=lambda item: item[0])
                                write(''.join( i[1] for i in section_items ))
                            write(line)
                            deal_stack.pop()
                        return end_match
                    section_item_key_group = 3 if section_name in pbx_section_names_sort_by_name else 2
                    def deal_section_line(line):
                        if check_end(line): return
                        section_item_match = pbx_section_item_ptn.search(line)
                        if section_item_match:
                            section_item_key = section_item_match.group(section_item_key_group)
                            if not section_item_key: section_item_key = ""
                            if section_item_match.group(4): # oneline item
                                section_items.append((section_item_key, line))
                            else: # multiline item
                                lines = [line]
                                end_ptn = re_compile(pbx_section_item_end_ptn.format(space=section_item_match.group(1)))
                                should_sort_children = section_item_match.group(2) not in children_nosort_group
                                def check_item_end(line):
                                    end_match = bool(end_ptn.search(line))
                                    if end_match:
                                        write(line)
                                        section_items.append((section_item_key, ''.join(lines)))
                                        output_stack.pop()
                                        deal_stack.pop()
                                    return end_match
                                def deal_section_item_line(line):
                                    if check_item_end(line): return
                                    if should_sort_children and (check_files(line) or check_children(line)):
                                        return
                                    write(line)
                                output_stack.append(lambda line: lines.append(line))
                                deal_stack.append(deal_section_item_line)
                        elif empty_line_ptn.search(line): pass
                        else: raise XUniqueExit("unexpected line:\n{}".format(line))
                    deal_stack.append(deal_section_line)
                return True
            return False
        def check_files(line):
            files_match = files_start_ptn.search(line)
            if files_match:
                write(line)
                lines = []
                end_ptn = re_compile(array_end_ptn.format(space=files_match.group(1)))
                def deal_files(line):
                    if end_ptn.search(line):
                        if lines:
                            lines.sort(key=lambda file_str: files_key_ptn.search(file_str).group())
                            write(''.join(lines))
                        write(line)
                        deal_stack.pop()
                    elif files_key_ptn.search(line):
                        if line in lines: removed_lines.append(line)
                        else: lines.append(line)
                    elif empty_line_ptn.search(line): pass
                    else: raise XUniqueExit("unexpected line:\n{}".format(line))
                deal_stack.append(deal_files)
                return True
            return False
        def check_children(line):
            children_match = children_start_ptn.search(line)
            if children_match:
                write(line)
                lines = []
                end_ptn = re_compile(array_end_ptn.format(space=children_match.group(1)))
                def deal_children(line):
                    if end_ptn.search(line):
                        if lines:
                            lines.sort(key=file_dir_order)
                            write(''.join(lines))
                        write(line)
                        deal_stack.pop()
                    elif children_pbx_key_ptn.search(line):
                        if line in lines: removed_lines.append(line)
                        else: lines.append(line)
                    elif empty_line_ptn.search(line): pass
                    else: raise XUniqueExit("unexpected line:\n{}".format(line))
                deal_stack.append(deal_children)
                return True
            return False
        def deal_global_line(line):
            if check_section(line) or check_files(line) or check_children(line):
                return
            write(line)
        deal_stack.append(deal_global_line)
        try:
            for line in fi_input(self.xcode_pbxproj_path, backup='.sbak', inplace=1):
                # project.pbxproj is an utf-8 encoded file
                line = decoded_string(line, 'utf-8')
                deal(line)
            assert len(deal_stack) == 1 and len(output_stack) == 1
        except Exception as e:
            fi_close()
            tmp_path = self.xcode_pbxproj_path + '.sbak'
            unlink(self.xcode_pbxproj_path)
            rename(tmp_path, self.xcode_pbxproj_path)
            raise e
        fi_close()
        tmp_path = self.xcode_pbxproj_path + '.sbak'
        if filecmp_cmp(self.xcode_pbxproj_path, tmp_path, shallow=False):
            unlink(self.xcode_pbxproj_path)
            rename(tmp_path, self.xcode_pbxproj_path)
            warning_print('Ignore sort, no changes made to "', self.xcode_pbxproj_path, sep='')
        else:
            unlink(tmp_path)
            self._is_modified = True
            success_print('Sort done')
            if removed_lines:
                warning_print('Following lines were deleted because of duplication:')
                print_ng(*removed_lines, end='')

    def __unique_project(self, project_hex):
        """PBXProject. It is root itself, no parents to it"""
        self.vprint('uniquify PBXProject')
        self.vprint('uniquify PBX*Group and PBX*Reference*')
        self.__unique_group_or_ref(project_hex, self.main_group_hex)
        self.vprint('uniquify XCConfigurationList')
        bcl_hex = self.root_node['buildConfigurationList']
        self.__unique_build_configuration_list(project_hex, bcl_hex)
        subprojects_list = self.root_node.get('projectReferences')
        if subprojects_list:
            self.vprint('uniquify Subprojects')
            for subproject_dict in subprojects_list:
                product_group_hex = subproject_dict['ProductGroup']
                project_ref_parent_hex = subproject_dict['ProjectRef']
                self.__unique_group_or_ref(project_ref_parent_hex, product_group_hex)
        targets_list = self.root_node['targets']
        # workaround for PBXTargetDependency referring target that have not been iterated
        for target_hex in targets_list:
            cur_path_key = ('productName', 'name')
            self.__set_to_result(project_hex, target_hex, cur_path_key)
        for target_hex in targets_list:
            self.__unique_target(target_hex)

    def __unique_build_configuration_list(self, parent_hex, build_configuration_list_hex):
        """XCConfigurationList"""
        cur_path_key = 'defaultConfigurationName'
        self.__set_to_result(parent_hex, build_configuration_list_hex, cur_path_key)
        build_configuration_list_node = self.nodes[build_configuration_list_hex]
        self.vprint('uniquify XCConfiguration')
        for build_configuration_hex in build_configuration_list_node['buildConfigurations']:
            self.__unique_build_configuration(build_configuration_list_hex, build_configuration_hex)

    def __unique_build_configuration(self, parent_hex, build_configuration_hex):
        """XCBuildConfiguration"""
        cur_path_key = 'name'
        self.__set_to_result(parent_hex, build_configuration_hex, cur_path_key)

    def __unique_target(self, target_hex):
        """PBXNativeTarget PBXAggregateTarget"""
        self.vprint('uniquify PBX*Target')
        current_node = self.nodes[target_hex]
        bcl_hex = current_node['buildConfigurationList']
        self.__unique_build_configuration_list(target_hex, bcl_hex)
        dependencies_list = current_node.get('dependencies')
        if dependencies_list:
            self.vprint('uniquify PBXTargetDependency')
            for dependency_hex in dependencies_list:
                self.__unique_target_dependency(target_hex, dependency_hex)
        build_phases_list = current_node['buildPhases']
        for build_phase_hex in build_phases_list:
            self.__unique_build_phase(target_hex, build_phase_hex)
        build_rules_list = current_node.get('buildRules')
        if build_rules_list:
            for build_rule_hex in build_rules_list:
                self.__unique_build_rules(target_hex, build_rule_hex)

    def __unique_target_dependency(self, parent_hex, target_dependency_hex):
        """PBXTargetDependency"""
        target_hex = self.nodes[target_dependency_hex].get('target')
        if target_hex:
            self.__set_to_result(parent_hex, target_dependency_hex, self.__result[target_hex]['path'])
        else:
            self.__set_to_result(parent_hex, target_dependency_hex, 'name')
        target_proxy = self.nodes[target_dependency_hex].get('targetProxy')
        if target_proxy:
            self.__unique_container_item_proxy(target_dependency_hex, target_proxy)
        else:
            raise XUniqueExit('PBXTargetDependency item "', target_dependency_hex,
                              '" is invalid due to lack of "targetProxy" attribute')

    def __unique_container_item_proxy(self, parent_hex, container_item_proxy_hex):
        """PBXContainerItemProxy"""
        self.vprint('uniquify PBXContainerItemProxy')
        new_container_item_proxy_hex = self.__set_to_result(parent_hex, container_item_proxy_hex, ('isa', 'remoteInfo'))
        cur_path = self.__result[container_item_proxy_hex]['path']
        current_node = self.nodes[container_item_proxy_hex]
        # re-calculate remoteGlobalIDString to a new length 32 MD5 digest
        remote_global_id_hex = current_node.get('remoteGlobalIDString')
        append_warning = lambda: self.__result.setdefault('uniquify_warning', []).append(
            "PBXTargetDependency '{}' and its child PBXContainerItemProxy '{}' are not needed anymore, please remove their sections manually".format(
                self.__result[parent_hex]['new_key'], new_container_item_proxy_hex))
        if not remote_global_id_hex: append_warning()
        elif remote_global_id_hex not in self.__result:
            portal_hex = current_node['containerPortal']
            portal_result_hex = self.__result.get(portal_hex)
            if not portal_result_hex: append_warning()
            else:
                portal = self.nodes[portal_hex]
                if portal.get('path'):
                    abspath = path.join(self.xcodeproj_path, '..', portal['path'])
                    if abspath == self.xcodeproj_path: return # current project proxy. ignore it
                    info = current_node.get('remoteInfo')
                    if info is None: append_warning(); return

                    subproject = self.subproject(abspath)
                    proxyType = int(current_node.get('proxyType', -1))
                    if proxyType == 1:
                        self.__result[remote_global_id_hex] = {
                            'new_key': next((v for v in subproject.root_node['targets']
                                             if subproject.nodes[v]['name'] == info),
                                            remote_global_id_hex)}
                    elif proxyType == 2:
                        self.__result[remote_global_id_hex] = {
                            'new_key': next((subproject.nodes[v]['productReference'] for v in subproject.root_node['targets']
                                             if subproject.nodes[v]['name'] == info),
                                            remote_global_id_hex)}
                    else: # unknown type, ignore it
                        self.__result.setdefault('uniquify_warning', []).append(
                            "PBXContainerItemProxy '{}' has unsupported proxyType. don't unique it".format(
                                remote_global_id_hex))
                        self.__result[remote_global_id_hex] = {'new_key': remote_global_id_hex}

    def __unique_build_phase(self, parent_hex, build_phase_hex):
        """PBXSourcesBuildPhase PBXFrameworksBuildPhase PBXResourcesBuildPhase
        PBXCopyFilesBuildPhase PBXHeadersBuildPhase PBXShellScriptBuildPhase
        """
        self.vprint('uniquify all kinds of PBX*BuildPhase')
        current_node = self.nodes[build_phase_hex]
        # no useful key in some build phase types, use its isa value
        bp_type = current_node['isa']
        if bp_type == 'PBXShellScriptBuildPhase':
            cur_path_key = 'shellScript'
        elif bp_type == 'PBXCopyFilesBuildPhase':
            cur_path_key = ['name', 'dstSubfolderSpec', 'dstPath']
            if not current_node.get('name'):
                del cur_path_key[0]
        else:
            cur_path_key = bp_type
        self.__set_to_result(parent_hex, build_phase_hex, cur_path_key)
        self.vprint('uniquify PBXBuildFile')
        for build_file_hex in current_node['files']:
            self.__unique_build_file(build_phase_hex, build_file_hex)

    def __unique_group_or_ref(self, parent_hex, group_ref_hex):
        """PBXFileReference PBXGroup PBXVariantGroup PBXReferenceProxy"""
        if self.nodes.get(group_ref_hex):
            current_hex = group_ref_hex
            if self.nodes[current_hex].get('name'):
                cur_path_key = 'name'
            elif self.nodes[current_hex].get('path'):
                cur_path_key = 'path'
            else:
                # root PBXGroup has neither path nor name, give a new name 'PBXRootGroup'
                cur_path_key = 'PBXRootGroup'
            self.__set_to_result(parent_hex, current_hex, cur_path_key)
            if self.nodes[current_hex].get('children'):
                for child_hex in self.nodes[current_hex]['children']:
                    self.__unique_group_or_ref(current_hex, child_hex)
            if self.nodes[current_hex]['isa'] == 'PBXReferenceProxy':
                self.__unique_container_item_proxy(parent_hex, self.nodes[current_hex]['remoteRef'])
        else:
            self.vprint("Group/FileReference/ReferenceProxy '", group_ref_hex, "' not found, it will be removed.")
            self.__result.setdefault('to_be_removed', []).append(group_ref_hex)

    def __unique_build_file(self, parent_hex, build_file_hex):
        """PBXBuildFile"""
        current_node = self.nodes.get(build_file_hex)
        if not current_node:
            self.__result.setdefault('to_be_removed', []).append(build_file_hex)
        else:
            file_ref_hex = current_node.get('fileRef')
            if not file_ref_hex:
                self.vprint("PBXFileReference '", file_ref_hex, "' not found, it will be removed.")
                self.__result.setdefault('to_be_removed', []).append(build_file_hex)
            else:
                if self.__result.get(file_ref_hex):
                    cur_path_key = self.__result[file_ref_hex]['path']
                    self.__set_to_result(parent_hex, build_file_hex, cur_path_key)
                else:
                    self.vprint("PBXFileReference '", file_ref_hex, "' not found in PBXBuildFile '", build_file_hex,
                                "'. To be removed.", sep='')
                    self.__result.setdefault('to_be_removed', []).extend((build_file_hex, file_ref_hex))

    def __unique_build_rules(self, parent_hex, build_rule_hex):
        """PBXBuildRule"""
        current_node = self.nodes.get(build_rule_hex)
        if not current_node:
            self.vprint("PBXBuildRule '", current_node, "' not found, it will be removed.")
            self.__result.setdefault('to_be_removed', []).append(build_rule_hex)
        else:
            file_type = current_node['fileType']
            cur_path_key = 'fileType'
            if file_type == 'pattern.proxy':
                cur_path_key = ('fileType', 'filePatterns')
            self.__set_to_result(parent_hex, build_rule_hex, cur_path_key)


class XUniqueExit(SystemExit):
    def __init__(self, *args):
        arg_str = ''.join(args)
        value = "\x1B[31m{}\x1B[0m".format(arg_str)
        super(XUniqueExit, self).__init__(value)


def main():
    usage = "usage: %prog [-v][-u][-s][-c][-p] path/to/Project.xcodeproj"
    description = "Doc: https://github.com/truebit/xUnique"
    parser = OptionParser(usage=usage, description=description)
    parser.add_option("-v", "--verbose",
                      action="store_true", dest="verbose", default=False,
                      help="output verbose messages. default is False.")
    parser.add_option("-u", "--unique", action="store_true", dest="unique_bool", default=False,
                      help="uniquify the project file. default is False.")
    parser.add_option("-s", "--sort", action="store_true", dest="sort_bool", default=False,
                      help="sort the project file. default is False. When neither '-u' nor '-s' option exists, xUnique will invisibly add both '-u' and '-s' in arguments")
    parser.add_option("-c", "--combine-commit", action="store_true", dest="combine_commit", default=False,
                      help="When project file was modified, xUnique quit with 100 status. Without this option, the status code would be zero if so. This option is usually used in Git hook to submit xUnique result combined with your original new commit.")
    parser.add_option("-p", "--sort-pbx-by-filename", action="store_true", dest="sort_pbx_fn_bool", default=False,
                      help="sort PBXFileReference and PBXBuildFile sections in project file, ordered by file name. Without this option, ordered by MD5 digest, the same as Xcode does.")
    (options, args) = parser.parse_args(sys_argv[1:])
    if len(args) < 1:
        parser.print_help()
        raise XUniqueExit(
            "xUnique requires at least one positional argument: relative/absolute path to xcodeproj.")
    xcode_proj_path = decoded_string(args[0])
    xunique = XUnique(xcode_proj_path, options.verbose)
    if not (options.unique_bool or options.sort_bool):
        print_ng("Uniquify and Sort")
        xunique.unique_project()
        xunique.sort_pbxproj(options.sort_pbx_fn_bool)
        success_print("Uniquify and Sort done")
    else:
        if options.unique_bool:
            print_ng('Uniquify...')
            xunique.unique_project()
        if options.sort_bool:
            print_ng('Sort...')
            xunique.sort_pbxproj(options.sort_pbx_fn_bool)
    if options.combine_commit:
        if xunique.is_modified:
            warning_print("File 'project.pbxproj' was modified, please add it and then commit.")
            raise SystemExit(100)
    else:
        if xunique.is_modified:
            warning_print(
                "File 'project.pbxproj' was modified, please add it and commit again to submit xUnique result.\nNOTICE: If you want to submit xUnique result combined with original commit, use option '-c' in command.")


if __name__ == '__main__':
    main()
