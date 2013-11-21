# (C) British Crown Copyright 2011 - 2013, Met Office
# 
# This file is part of metOcean-mapping.
# 
# metOcean-mapping is free software: you can redistribute it and/or 
# modify it under the terms of the GNU Lesser General Public License 
# as published by the Free Software Foundation, either version 3 of 
# the License, or (at your option) any later version.
# 
# metOcean-mapping is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Lesser General Public License for more details.
# 
# You should have received a copy of the GNU Lesser General Public License
# along with metOcean-mapping. If not, see <http://www.gnu.org/licenses/>.


import glob
import json
import os
import socket
import subprocess
import sys
import time
import urllib
import urllib2

import metocean
import metocean.prefixes as prefixes


# Configure the Apache Jena environment.
if metocean.site_config.get('jena_dir') is not None:
    os.environ['JENAROOT'] = metocean.site_config['jena_dir']
else:
    msg = 'The Apache Jena semantic web framework has not been configured ' \
        'for metOcean.'
    raise ValueError(msg)

# Configure the Apache Fuseki environment.
if metocean.site_config.get('fuseki_dir') is not None:
    os.environ['FUSEKI_HOME'] = metocean.site_config['fuseki_dir']
else:
    msg = 'The Apache Fuseki SPARQL server has not been configured ' \
        'for metOcean.'
    raise ValueError(msg)


class FusekiServer(object):
    """
    A class to represent an instance of a process managing
    an Apache Jena triple store database and Fuseki SPARQL server.
    
    """
    def __init__(self, host='localhost', test=False):

        self._jena_dir = metocean.site_config['jena_dir']
        self._fuseki_dir = metocean.site_config['fuseki_dir']

        static_key = 'static_dir'
        tdb_key = 'tdb_dir'
        if test:
            static_key = 'test_{}'.format(static_key)
            tdb_key = 'test_{}'.format(tdb_key)
        
        if metocean.site_config.get(static_key) is None:
            msg = 'The {}static data directory for the Apache Jena database' \
                'has not been configured for metOcean.'
            raise ValueError(msg.format('test ' if test else ''))
        else:
            self._static_dir = metocean.site_config[static_key]

        if metocean.site_config.get(tdb_key) is None:
            msg = 'The Apache Jena {}triple store database directory has not ' \
                'been configured for metOcean.'
            raise ValueError(msg.format('test ' if test else ''))
        else:
            self._tdb_dir = metocean.site_config[tdb_key]
        
        self._fuseki_dataset = metocean.site_config['fuseki_dataset']

        port_key = 'port'
        if test:
            port_key = 'test_{}'.format(port_key)
        self.port = metocean.site_config[port_key]

        self.host = host
        self.test = test
        self._process = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()
        
    def start(self):
        """
        Initialise the Apache Fuseki SPARQL server process on the configured
        port, using the configured Apache Jena triple store database.
        
        """
        if not self.alive():
            nohup_dir = metocean.site_config['root_dir']
            if self.test:
                nohup_dir = metocean.site_config['test_dir']
            nohup_file = os.path.join(nohup_dir, 'nohup.out')
            if os.path.exists(nohup_file):
                os.remove(nohup_file)
            cwd = os.getcwd()
            os.chdir(nohup_dir)
            args = ['nohup',
                    os.path.join(self._fuseki_dir, 'fuseki-server'),
                    '--loc={}'.format(self._tdb_dir),
                    '--update',
                    '--port={}'.format(self.port),
                    self._fuseki_dataset]
            self._process = subprocess.Popen(args)
            os.chdir(cwd)
            for attempt in xrange(metocean.site_config['timeout_attempts']):
                if self.alive():
                    break
                time.sleep(metocean.site_config['timeout_sleep'])
            else:
                msg = 'The metOcean Apache Fuseki SPARQL server failed ' \
                    'to start.'
                raise RuntimeError(msg)

    def stop(self, save=False):
        """
        Shutdown the metOcean Apache Fuseki SPARQL server.

        Kwargs:
        * save:
            Save any cache results to the configured Apache Jena triple
            store database.
            
        """
        if save:
            self.save()
        if self.alive():
            pid = self._process.pid
            self._process.terminate()
            for attempt in xrange(metocean.site_config['timeout_attempts']):
                if not self.alive():
                    break
                time.sleep(metocean.site_config['timeout_sleep'])
            else:
                msg = 'The metOcean Apache Fuseki SPARQL server failed ' \
                    'to shutdown, PID={}.'
                raise RuntimeError(msg.format(pid))
                             
            self._process = None

    def restart(self):
        """
        Restart the metOcean Apache Fuseki SPARQL server.

        """
        self.stop()
        self.start()

    def alive(self):
        """
        Determine whether the Apache Fuseki SPARQL server is available
        on the configured port.

        Returns:
            Boolean.

        """
        result = False
        s = socket.socket() 
        try: 
            s.connect((self.host, self.port))
            s.close()
            result = True
        except socket.error:
            pass
        if result and self._process is None:
            msg = 'There is currently another service on port {!r}.'
            raise RuntimeError(msg.format(self.port))
        return result

    def clean(self):
        """
        Delete all of the files in the configured Apache Jena triple
        store database.

        """
        if self.alive():
            self.stop()
        files = os.path.join(self._tdb_dir, '*')
        for tdb_file in glob.glob(files):
            os.remove(tdb_file)
        return glob.glob(files)

    def save(self):
        """
        write out all saveCache flagged changes in the metocean graph,
        appending to the relevant ttl files
        remove saveCache flags after saving
        
        """
        
        main_graph = metocean.site_config['graph']
        files = os.path.join(self._static_dir, main_graph, '*.ttl')
        for subgraph in glob.glob(files):
            graph = 'http://%s/%s' % (main_graph, subgraph.split('/')[-1])
            save_string = self.save_cache(graph)
            with open(subgraph, 'a') as sg:
                for line in save_string.splitlines():
                    if not line.startswith('@prefix'):
                        sg.write(line)
                        sg.write('\n')



    def save_cache(self, graph, debug=False):
        """
        export new records from a graph in the triple store to an external location,
        as flagged by the manager application
        clear the 'not saved' flags on records, updating a graph in the triple store
        with the fact that changes have been persisted to ttl

        """
        qstr = '''
        CONSTRUCT
        {
            ?s ?p ?o .
        }
        WHERE
        {
        GRAPH <%s>
        {
        ?s ?p ?o ;
            mr:saveCache "True" .
        }
        } 
        ''' % graph
        results = self.run_query(qstr, output="text", debug=debug)
        qstr = '''
        DELETE
        {  GRAPH <%s>
            {
            ?s mr:saveCache "True" .
            }
        }
        WHERE
        {  GRAPH <%s>
            {
        ?s ?p ?o ;
            mr:saveCache "True" .
            }
        } 
        ''' % (graph,graph)
        delete_results = self.run_query(qstr, update=True, debug=debug)
        save_string = ''
        for line in results.split('\n'):
            if not line.strip().startswith('mr:saveCache'):
                save_string += line
                save_string += '\n'
            else:
                if line.endswith('.'):
                    save_string += '\t.\n'
        return save_string


    def revert(self):
        """
        identify all cached changes in the metocean graph
        and remove them, reverting the TDB to the same state
        as the saved ttl files
        
        """
        qstr = '''
        DELETE
        {  GRAPH <%s>
            {
            ?s ?p ?o .
            }
        }
        WHERE
        {  GRAPH <%s>
            {
            ?s ?p ?o ;
            mr:saveCache "True" .
            }
        } 
        '''
        main_graph = metocean.site_config['graph']
        files = os.path.join(self._static_dir, main_graph, '*.ttl')
        for infile in glob.glob(files):
            ingraph = infile.split('/')[-1]
            graph = 'http://%s/%s' % (main_graph, ingraph)
            qstring = qstr % (graph, graph)
            revert_string = self.run_query(qstring, update=True)

    def query_cache(self):
        """
        identify all cached changes in the metocean graph

        """
        qstr = '''
        SELECT ?s ?p ?o
        WHERE
        {  GRAPH <%s>
            {
        ?s ?p ?o ;
            mr:saveCache "True" .
            }
        } 
        '''
        results = []
        main_graph = metocean.site_config['graph']
        files = os.path.join(self._static_dir, main_graph, '*.ttl')
        for infile in glob.glob(files):
            ingraph = infile.split('/')[-1]
            graph = 'http://%s/%s' % (main_graph, ingraph)
            query_string = qstr % (graph)
            result = self.run_query(query_string)
            results = results + result
        return results


    def load(self):
        """
        Load all the static data turtle files into the new Apache Jena
        triple store database.

        """
        self.clean()
        graphs = os.path.join(self._static_dir, '*')
        for ingraph in glob.glob(graphs):
            graph = ingraph.split('/')[-1]
            subgraphs = os.path.join(ingraph, '*.ttl')
            for insubgraph in glob.glob(subgraphs):
                subgraph = insubgraph.split('/')[-1]
                tdb_load = [os.path.join(self._jena_dir, 'bin/tdbloader'),
                            '--graph=http://{}/{}'.format(graph, subgraph),
                            '--loc={}'.format(self._tdb_dir),
                            insubgraph]
                print ' '.join(tdb_load)
                subprocess.check_call(tdb_load)

    def validate(self):
        """
        run the validation queries

        """
        failures = {}
        mm_string = 'The following mappings are ambiguous, providing multiple '\
                    'targets in the same format for a particular source'
        failures[mm_string] = self.run_query(multiple_mappings())
        invalid_vocab = 'The following mappings contain an undeclared URI'
        failures[invalid_vocab] = self.run_query(valid_vocab())
        return failures

    def run_query(self, query_string, output='json', update=False, debug=False):
        """
        run a query_string on the FusekiServer instance
        return the results
        
        """
        if not self.alive():
            self.restart()
        # use null ProxyHandler to ignore proxy for localhost access
        proxy_support = urllib2.ProxyHandler({})
        opener = urllib2.build_opener(proxy_support)
        urllib2.install_opener(opener)
        pre = prefixes.Prefixes()
        if debug == True:
            k=0
            for j, line in enumerate(pre.sparql.split('\n')):
                print j,line
                k+=1
            for i, line in enumerate(query_string.split('\n')):
                print i+k, line
        if update:
            action = 'update'
            qstr = urllib.urlencode([
                (action, "%s %s" % (pre.sparql, query_string))])
        else:
            action = 'query'
            qstr = urllib.urlencode([
                (action, "%s %s" % (pre.sparql, query_string)),
                ("output", output),
                ("stylesheet","/static/xml-to-html-links.xsl")])
        BASEURL = "http://%s:%i%s/%s?" % (self.host, self.port,
                                          self._fuseki_dataset, action)
        data = ''
        try:
            data = opener.open(urllib2.Request(BASEURL), qstr).read()
        except urllib2.URLError as err:
            ec = 'Error connection to Fuseki server on {}.\n server returned {}'
            ec = ec.format(BASEURL, err)
            raise RuntimeError(ec)
        if output == "json":
            return process_data(data)
        elif output == "text":
            return data
        else:
            return data

    def get_label(self, subject, debug=False):
        """
        return the skos:notation for a subject, if it exists

        """
        subject = str(subject)
        if not subject.startswith('<') and not subject.startswith('"'):
            subj_str = '"{}"'.format(subject)
        else:
            subj_str = subject
        qstr = ''' SELECT ?notation 
        WHERE { {'''
        for graph in _vocab_graphs():
            qstr += '\n\tGRAPH %s {' % graph
            qstr += '\n\t?s skos:notation ?notation . }}\n\tUNION {'
        qstr = qstr.rstrip('\n\tUNION {')
        qstr += '\n\tFILTER(?s = %(sub)s) }' % {'sub':subj_str}
        results = self.run_query(qstr, debug=debug)
        if len(results) == 0:
            hash_split = subject.split('#')
            if len(hash_split) == 2 and hash_split[1].endswith('>'):
                label = hash_split[1].rstrip('>')
            else:
                # raise ValueError('{} returns no notation'.format(subject))
                label = subject
        elif len(results) >1:
            raise ValueError('{} returns multiple notation'.format(subject))
        else:
            label = results[0]['notation']
        return label

    def get_contacts(self, register, debug=False):
        """
        return a list of contacts from the tdb which are part of the named register

        """
        qstr = '''
        SELECT ?s ?prefLabel ?def
        WHERE
        { GRAPH <http://metarelate.net/contacts.ttl> {
            ?s skos:inScheme <http://www.metarelate.net/metOcean/%s> ;
               skos:prefLabel ?prefLabel ;
               skos:definition ?def ;
               dc:valid ?valid .
        } }
        ''' % register
        results = self.run_query(qstr, debug=debug)
        return results

    def subject_and_plabel(self, graph, debug=False):
        """
        selects subject and prefLabel from a particular graph

        """
        qstr = '''
            SELECT ?subject ?prefLabel ?notation
            WHERE {
                GRAPH <%s> {
                ?subject skos:notation ?notation .
                OPTIONAL {?subject skos:prefLabel ?prefLabel . }}
            }
            ORDER BY ?subject
        ''' % graph
        results = self.run_query(qstr, debug=debug)
        return results

    # def retrieve_mappings(self, source, target):
    #     """
    #     return the format specific mappings for a particular source
    #     and target format

    #     """
    #     if isinstance(source, basestring) and \
    #             not metocean.Item(source).is_uri():
    #         source = os.path.join('<http://www.metarelate.net/metOcean/format',
    #                               '{}>'.format(source.lower()))
    #     if isinstance(target, basestring) and \
    #             not metocean.Item(target).is_uri():
    #         target = os.path.join('<http://www.metarelate.net/metOcean/format',
    #                               '{}>'.format(target.lower()))
    #     qstr = '''
    #     SELECT ?mapping ?source ?sourceFormat ?target ?targetFormat ?inverted
    #     (GROUP_CONCAT(DISTINCT(?valueMap); SEPARATOR = '&') AS ?valueMaps)
    #     WHERE { 
    #     GRAPH <http://metarelate.net/mappings.ttl> { {
    #     ?mapping mr:source ?source ;
    #              mr:target ?target ;
    #              mr:status ?status .
    #     BIND("False" AS ?inverted)
    #     OPTIONAL {?mapping mr:hasValueMap ?valueMap . }
    #     FILTER (?status NOT IN ("Deprecated", "Broken"))
    #     MINUS {?mapping ^dc:replaces+ ?anothermap}
    #     }
    #     UNION {
    #     ?mapping mr:source ?target ;
    #              mr:target ?source ;
    #              mr:status ?status ;
    #              mr:invertible "True" .
    #     BIND("True" AS ?inverted)
    #     OPTIONAL {?mapping mr:hasValueMap ?valueMap . }
    #     FILTER (?status NOT IN ("Deprecated", "Broken"))
    #     MINUS {?mapping ^dc:replaces+ ?anothermap}
    #     } }
    #     GRAPH <http://metarelate.net/concepts.ttl> { 
    #     ?source mr:hasFormat %s .
    #     ?target mr:hasFormat %s .
    #     }
    #     }
    #     GROUP BY ?mapping ?source ?sourceFormat ?target ?targetFormat ?inverted
    #     ORDER BY ?mapping

    #     ''' % (source, target)
    #     mappings = self.run_query(qstr)
    #     mapping_list = []
    #     for mapping in mappings:
    #         mapping_list.append(self.structured_mapping(mapping))
    #     return mapping_list

    def _retrieve_component(self, uri, base=True):
        qstr = metocean.Component.sparql_retriever(uri)
        qcomp = self.retrieve(qstr)
        if qcomp is None:
            msg = 'Cannot retrieve URI {!r} from triple-store.'
            raise ValueError(msg.format(uri))
        for key in ['property', 'subComponent']:
            if qcomp.get(key) is None:
                qcomp[key] = []
            if isinstance(qcomp[key], basestring):
                qcomp[key] = [qcomp[key]]
        if qcomp['property']:
            properties = []
            for puri in qcomp['property']:
                qstr = metocean.Property.sparql_retriever(puri)
                qprop = self.retrieve(qstr)
                name = qprop['name']
                name = metocean.Item(name, self.get_label(name))
                curi = qprop.get('component')
                if curi is not None:
                    value = self._retrieve_component(curi, base=False)
                else:
                    value = qprop.get('value')
                    if value is not None:
                        value = metocean.Item(value, self.get_label(value))
                    op = qprop.get('operator')
                    if op is not None:
                        op = metocean.Item(op, self.get_label(op))
                properties.append(metocean.Property(puri, name, value, op))
            result = metocean.PropertyComponent(uri, properties)
        if qcomp['subComponent']:
            components = []
            for curi in qcomp['subComponent']:
                components.append(self._retrieve_component(curi, base=False))
            if base:
                result = components
            else:
                result = metocean.Component(uri, components)
        if base:
            scheme = qcomp['format']
            scheme = metocean.Item(scheme, self.get_label(scheme))
            result = metocean.Concept(uri, scheme, result)
        return result

    def _retrieve_value_map(self, valmap_id, inv):
        """
        returns a dictionary of valueMap information
        
        """
        if inv == '"False"':
            inv = False
        elif inv == '"True"':
            inv = True
        else:
            raise ValueError('inv = {}, not "True" or "False"'.format(inv))
        value_map = {'valueMap':valmap_id, 'mr:source':{}, 'mr:target':{}}
        qstr = metocean.ValueMap.sparql_retriever(valmap_id)
        vm_record = self.retrieve(qstr)
        if inv:
            value_map['mr:source']['value'] = vm_record['target']
            value_map['mr:target']['value'] = vm_record['source']
        else:
            value_map['mr:source']['value'] = vm_record['source']
            value_map['mr:target']['value'] = vm_record['target']
        for role in ['mr:source', 'mr:target']:
            value_map[role] = self._retrieve_value(value_map[role]['value'])

        return value_map

    def _retrieve_value(self, val_id):
        """
        returns a dictionary from a val_id
        
        """
        value_dict = {'value':val_id}
        qstr = metocean.Value.sparql_retriever(val_id)
        val = self.retrieve(qstr)
        for key in val.keys():
            value_dict['mr:{}'.format(key)] = val[key]
        for sc_prop in ['mr:subject', 'mr:object']:
            pid = value_dict.get(sc_prop)
            if pid:
                qstr = metocean.ScopedProperty.sparql_retriever(pid)
                prop = self.retrieve(qstr)
                if prop:
                    value_dict[sc_prop] = {}
                    for pkey in prop:
                        pv = prop[pkey]
                        value_dict[sc_prop]['mr:{}'.format(pkey)] = pv
                        if pkey == 'hasProperty':
                            pr = value_dict[sc_prop]['mr:{}'.format(pkey)]
                            qstr = metocean.Property.sparql_retriever(pr)
                            aprop = self.retrieve(qstr)
                            value_dict[sc_prop]['mr:{}'.format(pkey)] = {'property':pv}
                            for p in aprop:
                                value_dict[sc_prop]['mr:{}'.format(pkey)]['mr:{}'.format(p)] = aprop[p]
                elif pid.startswith('<http://www.metarelate.net/metOcean/value/'):
                    newval = self._retrieve_value(pid)
                    value_dict[sc_prop] = newval
                else:
                    value_dict[sc_prop] = pid
        return value_dict

    def structured_mapping(self, template):
        uri = template['mapping']
        source = self._retrieve_component(template['source'])
        target = self._retrieve_component(template['target'])
        return metocean.Mapping(uri, source, target)
    
    def retrieve(self, qstr, debug=False):
        """
        Return a record from the provided id
        or None if one does not exist.

        """
        results = self.run_query(qstr, debug=debug)
        if len(results) == 0:
            fCon = None
        elif len(results) >1:
            raise ValueError('{} is a malformed component'.format(results))
        else:
            fCon = results[0]
        return fCon

    def create(self, qstr, instr, debug=False):
        """obtain a json representation of a defined type
        either by retrieving or creating it
        qstr is a SPARQL query string 
        instr is a SPARQL insert string
        """
        results = self.run_query(qstr, debug=debug)
        if len(results) == 0:
            insert_results = self.run_query(instr, update=True, debug=debug)
            results = self.run_query(qstr, debug=debug)
        if len(results) == 1:
            results = results[0]
        else:
            ec = '{} results returned, one expected'.format(len(results))
            raise ValueError(ec)
        return results

    def mapping_by_properties(self, prop_list):
        results = self.run_query(mapping_by_properties(prop_list))
        mapping = None
        maps = set([r['mapping'] for r in results])
        if not mapping:
            mappings = maps
        else:
            mappings.intersection_update(maps)
        return mappings


def process_data(jsondata):
    """ helper method to take JSON output from a query and return the results"""
    resultslist = []
    try:
        jdata = json.loads(jsondata)
    except (ValueError, TypeError):
        return resultslist
    vars = jdata['head']['vars']
    data = jdata['results']['bindings']
    for item in data:
        tmpdict = {}
        for var in vars:
            tmpvar = item.get(var)
            if tmpvar:
                val = tmpvar.get('value')
                if str(val).startswith('http://') or \
                   str(val).startswith('https://') :
                    if len(val.split('&')) == 1:
                        val = '<{}>'.format(val)
                    else:
                        val = ['<{}>'.format(v) for v in val.split('&')]
                    # val = ['<{}>'.format(v) for v in val.split('&')]
                else:
                    try:
                        int(val)
                    except ValueError:
                        try:
                            float(val)
                        except ValueError:
                            if not val.startswith('<'):
                                val = '"{}"'.format(val)
                tmpdict[var] = val
        if tmpdict != {}:
            resultslist.append(tmpdict)
    return resultslist


def multiple_mappings(test_source=None):
    """
    returns all the mappings which map the same source to a different target
    where the targets are the same format
    filter to a single test mapping with test_map
    
    """
    tm_filter = ''
    if test_source:
        pattern = '<http.*>'
        pattern = re.compile(pattern)
        if pattern.match(test_source):
            tm_filter = '\n\tFILTER(?asource = {})'.format(test_source)
    qstr = '''SELECT ?amap ?asource ?atarget ?bmap ?bsource ?btarget
    (GROUP_CONCAT(DISTINCT(?value); SEPARATOR='&') AS ?signature)
    WHERE {
    GRAPH <http://metarelate.net/mappings.ttl> { {
    ?amap mr:status ?astatus ;
         mr:source ?asource ;
         mr:target ?atarget . } 
    UNION 
        { 
    ?amap mr:invertible "True" ;
         mr:status ?astatus ;
         mr:target ?asource ;
         mr:source ?atarget . } 
    FILTER (?astatus NOT IN ("Deprecated", "Broken"))
    MINUS {?amap ^dc:replaces+ ?anothermap} %s
    } 
    GRAPH <http://metarelate.net/mappings.ttl> { {
    ?bmap mr:status ?bstatus ;
         mr:source ?bsource ;
         mr:target ?btarget . } 
    UNION  
        { 
    ?bmap mr:invertible "True" ;
         mr:status ?bstatus ;
         mr:target ?bsource ;
         mr:source ?btarget . } 
    FILTER (?bstatus NOT IN ("Deprecated", "Broken"))
    MINUS {?bmap ^dc:replaces+ ?bnothermap}
    filter (?bmap != ?amap)
    filter (?bsource = ?asource)
    filter (?btarget != ?atarget)
    } 
    GRAPH <http://metarelate.net/concepts.ttl> {
    ?asource mr:hasFormat ?asourceformat .
    ?bsource mr:hasFormat ?bsourceformat .
    ?atarget mr:hasFormat ?atargetformat .
    ?btarget mr:hasFormat ?btargetformat .
    }
    filter (?btargetformat = ?atargetformat)
    GRAPH <http://metarelate.net/concepts.ttl> { {
    ?asource mr:hasProperty ?prop . }
    UNION {
    ?atarget mr:hasProperty ?prop . }
    UNION {
    ?asource mr:hasComponent|mr:hasProperty ?prop . }
    UNION {
    ?atarget mr:hasComponent|mr:hasProperty ?prop . }
    UNION { 
    ?asource mr:hasProperty|mr:hasComponent|mr:hasProperty ?prop . }
    UNION { 
    ?atarget mr:hasProperty|mr:hasComponent|mr:hasProperty ?prop . }
    OPTIONAL { ?prop rdf:value ?value . }
    } }
    GROUP BY ?amap ?asource ?atarget ?bmap ?bsource ?btarget
    ORDER BY ?asource
    ''' % tm_filter
    return qstr


def valid_vocab():
    """
    find all valid mapping and every property they reference

    """
    qstr = '''
    SELECT DISTINCT  ?amap 
    (GROUP_CONCAT(DISTINCT(?vocab); SEPARATOR = '&') AS ?signature)
    WHERE {      
    GRAPH <http://metarelate.net/mappings.ttl> { {  
    ?amap mr:status ?astatus ; 
    FILTER (?astatus NOT IN ("Deprecated", "Broken")) 
    MINUS {?amap ^dc:replaces+ ?anothermap}      }
    { 
    ?amap mr:source ?fc .      }
    UNION {
    ?amap mr:target ?fc .      } } 
    GRAPH <http://metarelate.net/concepts.ttl> { {
    ?fc mr:hasProperty ?prop . }
    UNION {
    ?fc mr:hasComponent|mr:hasProperty ?prop . }
    UNION { 
    ?fc mr:hasProperty|mr:hasComponent|mr:hasProperty ?prop .
    }
    { ?prop mr:name ?vocab . }
    UNION {
    ?prop mr:operator ?vocab . }
    UNION {
    ?prop rdf:value ?vocab . }
    FILTER(ISURI(?vocab))  }
    OPTIONAL {GRAPH ?g{?vocab ?p ?o .} }
    FILTER(!BOUND(?g))      }
    GROUP BY ?amap
    '''
    return qstr


def mapping_by_properties(prop_list):
    """
    Return the mapping id's which contain all of the proerties
    in the list of property dictionaries
    
    """
    for prop_dict in prop_list:
        fstr = ''
        name = prop_dict.get('mr:name')
        op = prop_dict.get('mr:operator')
        value = prop_dict.get('rdf:value')
        if name:
            fstr += '\tFILTER(?name = {})\n'.format(name)
        if op:
            fstr += '\tFILTER(?operator = {})\n'.format(op)
        if value:
            fstr += '\tFILTER(?value = {})\n'.format(value)
            
        qstr = '''SELECT DISTINCT ?mapping 
        WHERE {
        GRAPH <http://metarelate.net/mappings.ttl> {    
        ?mapping rdf:type mr:Mapping ;
                 mr:source ?source ;
                 mr:target ?target ;
                 mr:status ?status ;

        FILTER (?status NOT IN ("Deprecated", "Broken"))
        MINUS {?mapping ^dc:replaces+ ?anothermap}
        }
        GRAPH <http://metarelate.net/concepts.ttl> { {
        ?source mr:hasProperty ?property
        }
        UNION {
        ?target mr:hasProperty ?property
        }
        UNION {
        ?source mr:hasComponent/mr:hasProperty ?property
        }
        UNION {
        ?target mr:hasComponent/mr:hasProperty ?property
        }
        UNION {
        ?source mr:hasProperty/mr:hasComponent/mr:hasProperty ?property
        }
        UNION {
        ?target mr:hasProperty/mr:hasComponent/mr:hasProperty ?property
        }
        ?property mr:name ?name .
        OPTIONAL{?property rdf:value ?value . }
        OPTIONAL{?property mr:operator ?operator . }
        %s
        }
        }
        ''' % fstr
    return qstr


# def get_all_notation_note(fuseki_process, graph, debug=False):
#     """
#     return all names, skos:notes and skos:notations from the stated graph
#     """
#     qstr = '''SELECT ?name ?notation ?units
#     WHERE
#     {GRAPH <%s>{
#     ?name skos:note ?units ;
#           skos:notation ?notation .
#     }
#     }
#     order by ?name
#     ''' % graph
#     results = fuseki_process.run_query(qstr, debug=debug)
#     return results


def _vocab_graphs():
    """returns a list of the graphs which contain thirds party vocabularies """
    vocab_graphs = []
    vocab_graphs.append('<http://metarelate.net/formats.ttl>')
    vocab_graphs.append('<http://um/umdpF3.ttl>')
    vocab_graphs.append('<http://um/stashconcepts.ttl>')
    vocab_graphs.append('<http://um/fieldcode.ttl>')
    vocab_graphs.append('<http://cf/cf-model.ttl>')
    vocab_graphs.append('<http://cf/cf-standard-name-table.ttl>')
    vocab_graphs.append('<http://grib/apikeys.ttl>')
    vocab_graphs.append('<http://openmath/ops.ttl>')
    return vocab_graphs



class ValidMappingState(object):
    """
    A context manager providing the valid mappings only for the
    life of the context

    """
    def __init__(fuseki_process):
        self.fuseki_process = fuseki_process
        self.valid_state = False

    def __enter__(self):
        cache_len = len(self.fuseki_process.query_cache())
        self.entry_msg = ''
        if cache_len != 0:
            self.entry_msg = 'There are {} cached changes in the TDB'
            self.entry_msg += 'the valid mapping state cannot be used.'
            self.entry_msg += 'persist or revert the cache to use the'
            self.entry_msg += 'ValidMappingState.'
            self.entry_msg.format(cache_len)
        else:
            self.delete_invalid()
            self.valid_state = True
            self.entry_msg = 'Working with valid mappings only'
        return self
            
    def __exit__(self):
        self.exit_msg = ''
        if self.valid_state:
            self.fuseki_process.load()
            self.exit_msg = 'TDB re-synchronised with static data'
        else:
            self.exit_msg = 'TDB untouched'

    def delete_invalid(self):
        """
        remove all mapping which have been replaced or have do not
        have a status of 'draft, proposed or approved' from the TDB

        """
        instr = '''
        DELETE
        { GRAPH <http://metarelate.net/mappings.ttl> 
            {
            ?mapping ?p ?o .
            }
        }
        WHERE
        { GRAPH <http://metarelate.net/mappings.ttl> 
            { {
            ?mapping mr:status "Deprecated" .
            }
            UNION
            {
            ?mapping mr:status "Broken" .
            }
            UNION
            {
            ?mapping ^dc:replaces+ ?anothermap .
            }
            }
        }
        '''
        delete_results = self.run_query(instr, update=True, debug=debug)

    def retrieve_mappings(self, source, target):
        """
        return the format specific mappings for a particular source
        and target format

        """
        if isinstance(source, basestring) and \
                not metocean.Item(source).is_uri():
            source = os.path.join('<http://www.metarelate.net/metOcean/format',
                                  '{}>'.format(source.lower()))
        if isinstance(target, basestring) and \
                not metocean.Item(target).is_uri():
            target = os.path.join('<http://www.metarelate.net/metOcean/format',
                                  '{}>'.format(target.lower()))
        qstr = '''
        SELECT ?mapping ?source ?sourceFormat ?target ?targetFormat ?inverted
        (GROUP_CONCAT(DISTINCT(?valueMap); SEPARATOR = '&') AS ?valueMaps)
        WHERE { 
        GRAPH <http://metarelate.net/mappings.ttl> { {
        ?mapping mr:source ?source ;
                 mr:target ?target ;
                 mr:status ?status .
        BIND("False" AS ?inverted)
        OPTIONAL {?mapping mr:hasValueMap ?valueMap . }
        }
        UNION {
        ?mapping mr:source ?target ;
                 mr:target ?source ;
                 mr:status ?status ;
                 mr:invertible "True" .
        BIND("True" AS ?inverted)
        OPTIONAL {?mapping mr:hasValueMap ?valueMap . }
        } }
        GRAPH <http://metarelate.net/concepts.ttl> { 
        ?source mr:hasFormat %s .
        ?target mr:hasFormat %s .
        }
        }
        GROUP BY ?mapping ?source ?sourceFormat ?target ?targetFormat ?inverted
        ORDER BY ?mapping

        ''' % (source, target)
        mappings = self.fuseki_process.run_query(qstr)
        mapping_list = []
        for mapping in mappings:
            mapping_list.append(self.fuseki_process.structured_mapping(mapping))
        return mapping_list
