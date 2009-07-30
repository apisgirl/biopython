# Copyright (C) 2009 by Eric Talevich (eric.talevich@gmail.com)
# This code is part of the Biopython distribution and governed by its
# license. Please see the LICENSE file that should have been included
# as part of this package.

"""PhyloXML reader/parser, writer, and associated functions.

Instantiates Tree elements from a parsed PhyloXML file, and constructs an XML
file from a Tree.PhyloXML object.
"""
__docformat__ = "epytext en"

import sys
import warnings

from Bio.Tree import PhyloXML as Tree

try:
    from xml.etree import cElementTree as ElementTree
except ImportError:
    try:
        from xml.etree import ElementTree as ElementTree
    except ImportError:
        # Python 2.4 -- check for 3rd-party implementations
        try:
            from lxml.etree import ElementTree
        except ImportError:
            try:
                import cElementTree as ElementTree
            except ImportError:
                try:
                    from elementtree import ElementTree
                except ImportError:
                    from Bio import MissingExternalDependencyError
                    raise MissingExternalDependencyError(
                            "No ElementTree module was found. "
                            "Use Python 2.5+, lxml or elementtree if you "
                            "want to use Bio.PhyloXML.")

# Keep the standard namespace prefixes when writing
# See http://effbot.org/zone/element-namespaces.htm
NAMESPACES = {
        'phy':  'http://www.phyloxml.org',
        'xs':   'http://www.w3.org/2001/XMLSchema',
        }

try:
    register_namespace = ElementTree.register_namespace
except AttributeError:
    if not hasattr(ElementTree, '_namespace_map'):
        # cElementTree needs the pure-Python xml.etree.ElementTree
        # Py2.4 support: the exception handler can go away when Py2.4 does
        try:
            from xml.etree import ElementTree as ET_py
            ElementTree._namespace_map = ET_py._namespace_map
        except ImportError:
            warnings.warn("Couldn't import xml.etree.ElementTree; "
                    "phyloXML namespaces may have unexpected abbreviations "
                    "in the output.", RuntimeWarning, stacklevel=2)
            ElementTree._namespace_map = {}

    def register_namespace(prefix, uri):
        ElementTree._namespace_map[uri] = prefix

for prefix, uri in NAMESPACES.iteritems():
    register_namespace(prefix, uri)


class PhyloXMLError(Exception):
    """Exception raised when PhyloXML object construction cannot continue.

    XML syntax errors will be found and raised by the underlying ElementTree
    module; this exception is for valid XML that breaks the phyloXML
    specification.
    """
    pass


# ---------------------------------------------------------
# Functions I wish ElementTree had

def local(tag):
    """Extract the local tag from a namespaced tag name."""
    if tag[0] is '{':
        return tag[tag.index('}')+1:]
    return tag

def split_namespace(tag):
    """Split a tag into namespace and local tag strings."""
    try:
        return tag[1:].split('}', 1)
    except:
        return ('', tag)


def _ns(tag, namespace=NAMESPACES['phy']):
    """Format an XML tag with the given namespace."""
    return '{%s}%s' % (namespace, tag)

def get_child_as(parent, tag, construct):
    """Find a child node by tag, and pass it through a constructor.

    Returns None if no matching child is found.
    """
    child = parent.find(_ns(tag))
    if child is not None:
        return construct(child)

def get_child_text(parent, tag, construct=unicode):
    """Find a child node by tag; pass its text through a constructor.

    Returns None if no matching child is found.
    """
    child = parent.find(_ns(tag))
    if child is not None:
        return child.text and construct(child.text) or None

def get_children_as(parent, tag, construct):
    """Find child nodes by tag; pass each through a constructor.

    Returns None if no matching child is found.
    """
    return [construct(child) for child in 
            parent.findall(_ns(tag))]

def get_children_text(parent, tag, construct=unicode):
    """Find child nodes by tag; pass each node's text through a constructor.

    Returns None if no matching child is found.
    """
    return [construct(child.text) for child in 
            parent.findall(_ns(tag))
            if child.text]


def dump_tags(handle, file=sys.stdout):
    """Extract tags from an XML document, writing them to stdout by default.

    This utility is meant for testing and debugging.
    """
    for event, elem in ElementTree.iterparse(handle, events=('start', 'end')):
        if event == 'start':
            file.write(elem.tag + '\n')
        else:
            elem.clear()


# ---------------------------------------------------------
# Utilities

def str2bool(text):
    if text == 'true':
        return True
    if text == 'false':
        return False
    raise ValueError('String could not be converted to boolean: ' + text)

def dict_str2bool(dct, keys):
    out = dct.copy()
    for key in keys:
        if key in out:
            out[key] = str2bool(out[key])
    return out

def _int(text):
    if text is not None:
        try:
            return int(text)
        except Exception:
            return None

def _float(text):
    if text is not None:
        try:
            return float(text)
        except Exception:
            return None

def collapse_wspace(text):
    """Replace all spans of whitespace with a single space character.

    Also remove leading and trailing whitespace. See "Collapse Whitespace
    Policy" in the U{ phyloXML spec glossary
    <http://phyloxml.org/documentation/version_100/phyloxml.xsd.html#Glossary>
    }.
    """
    if text is not None:
        return ' '.join(text.split())

def replace_wspace(text):
    """Replace tab, LF and CR characters with spaces, but don't collapse.

    See "Replace Whitespace Policy" in the U{ phyloXML spec glossary
    <http://phyloxml.org/documentation/version_100/phyloxml.xsd.html#Glossary>
    }.
    """
    for char in ('\t', '\n', '\r'):
        if char in text:
            text = text.replace(char, ' ')
    return text


# ---------------------------------------------------------
# INPUT
# ---------------------------------------------------------

def read(file):
    """Parse a phyloXML file or stream and build a tree of Biopython objects.

    The children of the root node are phylogenies and possibly other arbitrary
    (non-phyloXML) objects.

    To minimize memory use, the tree of ElementTree parsing events is cleared
    after completing each phylogeny, clade, and top-level 'other' element.
    Elements below the clade level are kept in memory until parsing of the
    current clade is finished -- this shouldn't be a problem because clade is
    the main recursive element, and non-clade nodes below this level are of
    bounded size.

    @rtype: Bio.Tree.PhyloXML.Phyloxml
    """
    return Parser(file).read()


def parse(file):
    """Iterate over the phylogenetic trees in a phyloXML file.

    This ignores any additional data stored at the top level, but may be more
    memory-efficient than the read() function.

    @return: a generator of Bio.Tree.PhyloXML.Phylogeny objects.
    """
    return Parser(file).parse()


class Parser(object):
    """Methods for parsing all phyloXML nodes from an XML stream.
    """

    def __init__(self, file):
        # Get an iterable context for XML parsing events
        context = iter(ElementTree.iterparse(file, events=('start', 'end')))
        event, root = context.next()
        self.root = root
        self.context = context

    def read(self):
        """Parse the phyloXML file and create a single Phyloxml object."""
        phyloxml = Tree.Phyloxml(dict((local(key), val)
                                for key, val in self.root.items()))
        other_depth = 0
        for event, elem in self.context:
            namespace, localtag = split_namespace(elem.tag)
            if event == 'start':
                if namespace != NAMESPACES['phy']:
                    other_depth += 1
                    continue
                if localtag == 'phylogeny':
                    phylogeny = self._parse_phylogeny(elem)
                    phyloxml.phylogenies.append(phylogeny)
            if event == 'end' and namespace != NAMESPACES['phy']:
                # Deal with items not specified by phyloXML
                other_depth -= 1
                if other_depth == 0:
                    # We're directly under the root node -- evaluate
                    otr = self.to_other(elem)
                    phyloxml.other.append(otr)
                    self.root.clear()
        return phyloxml

    def parse(self):
        """Parse the phyloXML file incrementally and return each phylogeny."""
        phytag = _ns('phylogeny')
        for event, elem in self.context:
            if event == 'start' and elem.tag == phytag:
                yield self._parse_phylogeny(elem)

    # Special parsing cases

    def _parse_phylogeny(self, parent):
        """Parse a single phylogeny within the phyloXML tree.

        Recursively builds a phylogenetic tree with help from parse_clade, then
        clears the XML event history for the phylogeny element and returns
        control to the top-level parsing function.
        """
        phylogeny = Tree.Phylogeny(**dict_str2bool(parent.attrib,
                                                   ['rooted', 'rerootable']))
        complex_types = ['date', 'id']
        list_types = {
                # XML tag, plural attribute
                'confidence':   'confidences',
                'property':     'properties',
                'clade_relation': 'clade_relations',
                'sequence_relation': 'sequence_relations',
                }
        for event, elem in self.context:
            namespace, tag = split_namespace(elem.tag)
            if event == 'start' and tag == 'clade':
                assert phylogeny.clade is None, \
                        "Phylogeny object should only have 1 clade"
                phylogeny.clade = self._parse_clade(elem)
                continue
            if event == 'end':
                if tag == 'phylogeny':
                    parent.clear()
                    break
                # Handle the other non-recursive children
                if tag in complex_types:
                    setattr(phylogeny, tag, getattr(self, 'to_'+tag)(elem))
                elif tag in list_types:
                    getattr(phylogeny, list_types[tag]).append(
                            getattr(self, 'to_'+tag)(elem))
                # Simple types
                elif tag == 'name': 
                    phylogeny.name = collapse_wspace(elem.text)
                elif tag == 'description':
                    phylogeny.description = collapse_wspace(elem.text)
                # Unknown tags
                elif namespace != NAMESPACES['phy']:
                    phylogeny.other.append(self.to_other(elem))
                    parent.clear()
                else:
                    # NB: This shouldn't happen in valid files
                    raise PhyloXMLError('Misidentified tag: ' + tag)
        return phylogeny

    _clade_complex_types = ['color', 'events', 'binary_characters', 'date']
    _clade_list_types = {
            # XML tag, plural attribute
            'confidence':   'confidences',
            'taxonomy':     'taxonomies',
            'sequence':     'sequences',
            'distribution': 'distributions',
            'reference':    'references',
            'property':     'properties',
            }
    _clade_tracked_tags = set(_clade_complex_types + _clade_list_types.keys() +
            # Simple types
            ['branch_length', 'name', 'node_id', 'width'])

    def _parse_clade(self, parent):
        """Parse a Clade node and its children, recursively."""
        if 'branch_length' in parent.keys():
            parent.set('branch_length', float(parent.get('branch_length')))
        clade = Tree.Clade(**parent.attrib)
        # NB: Only evaluate nodes at the current level
        tag_stack = []
        for event, elem in self.context:
            namespace, tag = split_namespace(elem.tag)
            if event == 'start':
                if tag == 'clade':
                    subclade = self._parse_clade(elem)
                    clade.clades.append(subclade)
                    continue
                if tag in self._clade_tracked_tags:
                    tag_stack.append(tag)
            if event == 'end':
                if tag == 'clade':
                    elem.clear()
                    break
                if tag != tag_stack[-1]:
                    continue
                tag_stack.pop()
                # Handle the other non-recursive children
                if tag in self._clade_complex_types:
                    setattr(clade, tag, getattr(self, 'to_'+tag)(elem))
                elif tag in self._clade_list_types:
                    getattr(clade, self._clade_list_types[tag]).append(
                            getattr(self, 'to_'+tag)(elem))
                # Simple types
                elif tag == 'branch_length':
                    # NB: possible collision with the attribute
                    if hasattr(clade, 'branch_length') \
                            and clade.branch_length is not None:
                        raise PhyloXMLError(
                                'Attribute branch_length was already set '
                                'for this Clade; overwriting the previous '
                                'value.')
                    clade.branch_length = _float(elem.text)
                elif tag == 'width':
                    clade.width = _float(elem.text)
                elif tag == 'name':
                    clade.name = collapse_wspace(elem.text)
                elif tag == 'node_id':
                    clade.node_id = elem.text and elem.text.strip() or None
                # Unknown tags
                elif namespace != NAMESPACES['phy']:
                    clade.other.append(self.to_other(elem))
                    elem.clear()
                else:
                    # NB: This shouldn't happen in valid files
                    raise PhyloXMLError('Misidentified tag: ' + tag)
        return clade

    @classmethod
    def to_other(cls, elem):
        namespace, localtag = split_namespace(elem.tag)
        return Tree.Other(localtag, namespace, elem.attrib,
                  value=elem.text and elem.text.strip() or None,
                  children=[cls.to_other(child) for child in elem])

    # Complex types

    @classmethod
    def to_accession(cls, elem):
        return Tree.Accession(elem.text.strip(), elem.get('source'))

    @classmethod
    def to_annotation(cls, elem):
        return Tree.Annotation(
                desc=collapse_wspace(get_child_text(elem, 'desc')),
                confidence=get_child_as(elem, 'confidence', cls.to_confidence),
                properties=get_children_as(elem, 'property', cls.to_property),
                uri=get_child_as(elem, 'uri', cls.to_uri),
                **elem.attrib)

    @classmethod
    def to_binary_characters(cls, elem):
        def bc_getter(elem):
            return get_children_text(elem, 'bc')
        return Tree.BinaryCharacters(
                type=elem.get('type'),
                gained_count=_int(elem.get('gained_count')),
                lost_count=_int(elem.get('lost_count')),
                present_count=_int(elem.get('present_count')),
                absent_count=_int(elem.get('absent_count')),
                # Flatten BinaryCharacterList sub-nodes into lists of strings
                gained=get_child_as(elem, 'gained', bc_getter),
                lost=get_child_as(elem, 'lost', bc_getter),
                present=get_child_as(elem, 'present', bc_getter),
                absent=get_child_as(elem, 'absent', bc_getter))

    @classmethod
    def to_clade_relation(cls, elem):
        return Tree.CladeRelation(
                elem.get('type'), elem.get('id_ref_0'), elem.get('id_ref_1'),
                distance=elem.get('distance'),
                confidence=get_child_as(elem, 'confidence', cls.to_confidence))

    @classmethod
    def to_color(cls, elem):
        red, green, blue = (get_child_text(elem, color, int) for color in
                            ('red', 'green', 'blue'))
        return Tree.BranchColor(red, green, blue)

    @classmethod
    def to_confidence(cls, elem):
        return Tree.Confidence(
                _float(elem.text),
                elem.get('type'))

    @classmethod
    def to_date(cls, elem):
        return Tree.Date(
                unit=elem.get('unit'),
                desc=collapse_wspace(get_child_text(elem, 'desc')),
                value=get_child_text(elem, 'value', float),
                minimum=get_child_text(elem, 'minimum', float),
                maximum=get_child_text(elem, 'maximum', float),
                )

    @classmethod
    def to_distribution(cls, elem):
        return Tree.Distribution(
                desc=collapse_wspace(get_child_text(elem, 'desc')),
                points=get_children_as(elem, 'point', cls.to_point),
                polygons=get_children_as(elem, 'polygon', cls.to_polygon))

    @classmethod
    def to_domain(cls, elem):
        return Tree.ProteinDomain(elem.text.strip(),
                int(elem.get('from')) - 1,
                int(elem.get('to')),
                confidence=_float(elem.get('confidence')),
                id=elem.get('id'))

    @classmethod
    def to_domain_architecture(cls, elem):
        return Tree.DomainArchitecture(
                length=int(elem.get('length')),
                domains=get_children_as(elem, 'domain', cls.to_domain))

    @classmethod
    def to_events(cls, elem):
        return Tree.Events(
                type=get_child_text(elem, 'type'),
                duplications=get_child_text(elem, 'duplications', int),
                speciations=get_child_text(elem, 'speciations', int),
                losses=get_child_text(elem, 'losses', int),
                confidence=get_child_as(elem, 'confidence', cls.to_confidence))

    @classmethod
    def to_id(cls, elem):
        provider = elem.get('provider') or elem.get('type')
        return Tree.Id(elem.text.strip(), provider)

    @classmethod
    def to_mol_seq(cls, elem):
        is_aligned = elem.get('is_aligned')
        if is_aligned is not None:
            is_aligned = str2bool(is_aligned)
        return Tree.MolSeq(elem.text.strip(), is_aligned=is_aligned)

    @classmethod
    def to_point(cls, elem):
        return Tree.Point(
                elem.get('geodetic_datum'),
                get_child_text(elem, 'lat', float),
                get_child_text(elem, 'long', float),
                alt=get_child_text(elem, 'alt', float),
                alt_unit=elem.get('alt_unit'))

    @classmethod
    def to_polygon(cls, elem):
        return Tree.Polygon(
                points=get_children_as(elem, 'point', cls.to_point))

    @classmethod
    def to_property(cls, elem):
        return Tree.Property(elem.text.strip(),
                elem.get('ref'), elem.get('applies_to'), elem.get('datatype'),
                unit=elem.get('unit'),
                id_ref=elem.get('id_ref'))

    @classmethod
    def to_reference(cls, elem):
        return Tree.Reference(
                doi=elem.get('doi'),
                desc=get_child_text(elem, 'desc'))

    @classmethod
    def to_sequence(cls, elem):
        return Tree.Sequence(
                symbol=get_child_text(elem, 'symbol'),
                accession=get_child_as(elem, 'accession', cls.to_accession),
                name=collapse_wspace(get_child_text(elem, 'name')),
                location=get_child_text(elem, 'location'),
                mol_seq=get_child_as(elem, 'mol_seq', cls.to_mol_seq),
                uri=get_child_as(elem, 'uri', cls.to_uri),
                domain_architecture=get_child_as(elem, 'domain_architecture',
                                                 cls.to_domain_architecture),
                annotations=get_children_as(elem, 'annotation',
                                            cls.to_annotation),
                # TODO: handle "other"
                other=[],
                **elem.attrib)

    @classmethod
    def to_sequence_relation(cls, elem):
        return Tree.SequenceRelation(
                elem.get('type'), elem.get('id_ref_0'), elem.get('id_ref_1'),
                distance=_float(elem.get('distance')),
                confidence=get_child_as(elem, 'confidence', cls.to_confidence))

    @classmethod
    def to_taxonomy(cls, elem):
        return Tree.Taxonomy(
                id=get_child_as(elem, 'id', cls.to_id),
                code=get_child_text(elem, 'code'),
                scientific_name=get_child_text(elem, 'scientific_name'),
                authority=get_child_text(elem, 'authority'),
                common_names=get_children_text(elem, 'common_name'),
                synonyms=get_children_text(elem, 'synonym'),
                rank=get_child_text(elem, 'rank'),
                uri=get_child_as(elem, 'uri', cls.to_uri),
                # TODO: handle "other"
                other=[],
                **elem.attrib)

    @classmethod
    def to_uri(cls, elem):
        return Tree.Uri(elem.text.strip(),
                desc=collapse_wspace(elem.get('desc')),
                type=elem.get('type'))



# ---------------------------------------------------------
# OUTPUT
# ---------------------------------------------------------


def write(phyloxml, file, encoding=None):
    """Write a phyloXML file.

    The file argument can be either an open handle or a file name.
    """
    Writer(phyloxml, encoding).write(file)


# Helpers

def serialize(value):
    """Convert a Python primitive to a phyloXML-compatible Unicode string."""
    if isinstance(value, float):
        return unicode(value).upper()
    elif isinstance(value, bool):
        return unicode(value).lower()
    return unicode(value)


def _clean_attrib(obj, attrs):
    """Create a dictionary from an object's specified, non-None attributes."""
    out = {}
    for key in attrs:
        val = getattr(obj, key)
        if val is not None:
            out[key] = serialize(val)
    return out


def _handle_complex(tag, attribs, subnodes, has_text=False):
    def wrapped(self, obj):
        elem = ElementTree.Element(tag, _clean_attrib(obj, attribs))
        for subn in subnodes:
            if isinstance(subn, basestring):
                # singular object: method and attribute names are the same
                if getattr(obj, subn) is not None:
                    elem.append(getattr(self, subn)(getattr(obj, subn)))
            else:
                # list: singular method, pluralized attribute name
                method, plural = subn
                for item in getattr(obj, plural):
                    elem.append(getattr(self, method)(item))
        if has_text:
            elem.text = serialize(obj.value)
        return elem
    wrapped.__doc__ = "Serialize a %s and its subnodes, in order." % tag
    return wrapped


def _handle_simple(tag):
    def wrapped(self, obj):
        elem = ElementTree.Element(tag)
        elem.text = serialize(obj)
        return elem
    wrapped.__doc__ = "Serialize a simple %s node." % tag
    return wrapped


class Writer(object):
    """Methods for serializing a phyloXML object to XML.
    """
    def __init__(self, phyloxml, encoding):
        """Build an ElementTree from a phyloXML object."""
        assert isinstance(phyloxml, Tree.Phyloxml)
        self._tree = ElementTree.ElementTree(self.phyloxml(phyloxml))
        self.encoding = encoding

    def write(self, file):
        if self.encoding is not None:
            self._tree.write(file, self.encoding)
        else:
            self._tree.write(file)

    # Convert classes to ETree elements

    def phyloxml(self, obj):
        elem = ElementTree.Element(_ns('phyloxml'),
                # XXX not sure about this
                # {_ns('schemaLocation', NAMESPACES['xs']):
                #     obj.attributes['schemaLocation'],
                #     }
                )
        for tree in obj.phylogenies:
            elem.append(self.phylogeny(tree))
        for otr in obj.other:
            elem.append(self.other(otr))
        return elem

    def other(self, obj):
        elem = ElementTree.Element(_ns(obj.tag, obj.namespace), obj.attributes)
        elem.text = obj.value
        for child in obj.children:
            elem.append(self.other(child))
        return elem

    phylogeny = _handle_complex(_ns('phylogeny'),
            ('rooted', 'rerootable', 'branch_length_unit', 'type'),
            ( 'name',
              'id',
              'description',
              'date',
              ('confidence',        'confidences'),
              'clade',
              ('clade_relation',    'clade_relations'),
              ('sequence_relation', 'sequence_relations'),
              ('property',          'properties'),
              ('other',             'other'),
              ))

    clade = _handle_complex(_ns('clade'), ('id_source',),
            ( 'name',
              'branch_length',
              ('confidence',    'confidences'),
              'width',
              'color',
              'node_id',
              ('taxonomy',      'taxonomies'),
              ('sequence',      'sequences'),
              'events',
              'binary_characters',
              ('distribution',  'distributions'),
              'date',
              ('reference',     'references'),
              ('property',      'properties'),
              ('clade',         'clades'),
              ('other',         'other'),
              ))

    accession = _handle_complex(_ns('accession'), ('source',),
            (), has_text=True)

    annotation = _handle_complex(_ns('annotation'),
            ('ref', 'source', 'evidence', 'type'),
            ( 'desc',
              'confidence',
              ('property',   'properties'),
              'uri',
              ))

    def binary_characters(self, obj):
        """Serialize a binary_characters node and its subnodes."""
        elem = ElementTree.Element(_ns('binary_characters'),
                _clean_attrib(obj,
                    ('type', 'gained_count', 'lost_count',
                        'present_count', 'absent_count')))
        for subn in ('gained', 'lost', 'present', 'absent'):
            subelem = ElementTree.Element(_ns(subn))
            for token in getattr(obj, subn):
                subelem.append(self.bc(token))
            elem.append(subelem)
        return elem

    clade_relation = _handle_complex(_ns('clade_relation'),
            ('id_ref_0', 'id_ref_1', 'distance', 'type'),
            ('confidence',))

    color = _handle_complex(_ns('color'), (), ('red', 'green', 'blue'))

    confidence = _handle_complex(_ns('confidence'), ('type',),
            (), has_text=True)

    date = _handle_complex(_ns('date'), ('unit',),
            ('desc', 'value', 'minimum', 'maximum'))

    distribution = _handle_complex(_ns('distribution'), (),
            ( 'desc',
              ('point',     'points'),
              ('polygon',   'polygons'),
              ))

    def domain(self, obj):
        """Serialize a domain node."""
        elem = ElementTree.Element(_ns('domain'),
                {'from': str(obj.start + 1), 'to': str(obj.end)})
        if obj.confidence is not None:
            elem.set('confidence', serialize(obj.confidence))
        if obj.id is not None:
            elem.set('id', obj.id)
        elem.text = serialize(obj.value)
        return elem

    domain_architecture = _handle_complex(_ns('domain_architecture'),
            ('length',),
            (('domain', 'domains'),))

    events = _handle_complex(_ns('events'), (),
            ( 'type',
              'duplications',
              'speciations',
              'losses',
              'confidence',
              ))

    id = _handle_complex(_ns('id'), ('provider',), (), has_text=True)

    mol_seq = _handle_complex(_ns('mol_seq'), ('is_aligned',),
            (), has_text=True)

    node_id = _handle_complex(_ns('node_id'), ('provider',), (), has_text=True)

    point = _handle_complex(_ns('point'), ('geodetic_datum', 'alt_unit'),
            ('lat', 'long', 'alt'))

    polygon = _handle_complex(_ns('polygon'), (), (('point', 'points'),))

    property = _handle_complex(_ns('property'),
            ('ref', 'unit', 'datatype', 'applies_to', 'id_ref'),
            (), has_text=True)

    reference = _handle_complex(_ns('reference'), ('doi',), ('desc',))

    sequence = _handle_complex(_ns('sequence'),
            ('type', 'id_ref', 'id_source'),
            ( 'symbol',
              'accession',
              'name',
              'location',
              'mol_seq',
              'uri',
              ('annotation', 'annotations'),
              'domain_architecture',
              ('other', 'other'),
              ))

    sequence_relation = _handle_complex(_ns('sequence_relation'),
            ('id_ref_0', 'id_ref_1', 'distance', 'type'),
            ('confidence',))

    taxonomy = _handle_complex(_ns('taxonomy'),
            ('id_source',),
            ( 'id',
              'code',
              'scientific_name',
              'authority',
              ('common_name',   'common_names'),
              ('synonym',   'synonyms'),
              'rank',
              'uri',
              ('other',         'other'),
              ))

    uri = _handle_complex(_ns('uri'), ('desc', 'type'), (), has_text=True)

    # Primitive types

    # Floating point
    alt = _handle_simple(_ns('alt'))
    branch_length = _handle_simple(_ns('branch_length'))
    lat = _handle_simple(_ns('lat'))
    long = _handle_simple(_ns('long'))
    value = _handle_simple(_ns('value'))
    width = _handle_simple(_ns('width'))

    # Integers
    blue = _handle_simple(_ns('blue'))
    duplications = _handle_simple(_ns('duplications'))
    green = _handle_simple(_ns('green'))
    losses = _handle_simple(_ns('losses'))
    red = _handle_simple(_ns('red'))
    speciations = _handle_simple(_ns('speciations'))

    # Strings
    bc = _handle_simple(_ns('bc'))
    code = _handle_simple(_ns('code'))      # TaxonomyCode
    common_name = _handle_simple(_ns('common_name'))
    desc = _handle_simple(_ns('desc'))
    description = _handle_simple(_ns('description'))
    location = _handle_simple(_ns('location'))
    mol_seq = _handle_simple(_ns('mol_seq'))
    name = _handle_simple(_ns('name'))
    rank = _handle_simple(_ns('rank')) # Rank
    scientific_name = _handle_simple(_ns('scientific_name'))
    symbol = _handle_simple(_ns('symbol'))
    type = _handle_simple(_ns('type')) # EventType
