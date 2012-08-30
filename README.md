metOcean-mapping
================

These are the RDF Turtle datasets used by the mapping-manager

Running a SPARQL Endpoint
=========================

This project uses the fuseki SPARQL server to provide query access to the data.


Fuseki - http://jena.apache.org/documentation/serving_data/

    1. Download the 'jena-fuseki' release from http://www.apache.org/dist/jena/binaries/

    2. Unpack the archive

    3. Set environment variable FUSEKI_HOME to the path of the unpacked archive e.g. `export FUSEKI_HOME=${HOME}/java/jena-fuseki-0.2.4`


To run fuseki for the data, a Makefile is provided as part of the project:

    make load

    make start

will configure the environment and start the fuseki server
