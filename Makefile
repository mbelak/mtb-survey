# Byggen och tester. Kräver Connect IQ SDK:ns bin-mapp i PATH för build och test-watch,
# eller MONKEYC och MONKEYDO satta till full sökväg.
MONKEYC  ?= monkeyc
MONKEYDO ?= monkeydo
DEVICE   ?= epix2
DEVKEY   ?= developer_key

.PHONY: build package build-test test test-watch

build:                 ## bygg appen till bin/mtbsurveyepixgen2.prg
	"$(MONKEYC)" -f monkey.jungle -d $(DEVICE) -o bin/mtbsurveyepixgen2.prg -y "$(DEVKEY)" -r

package:               ## bygg paketet bin/mtbsurvey.iq för uppladdning till Connect IQ Store
	"$(MONKEYC)" -e -f monkey.jungle -o bin/mtbsurvey.iq -y "$(DEVKEY)" -r

build-test:            ## bygg testvarianten med enhetstesterna i test/
	"$(MONKEYC)" -f monkey.jungle -d $(DEVICE) -o bin/test.prg -y "$(DEVKEY)" -t

test-watch: build-test ## kör enhetstesterna i simulatorn (starta simulatorn först)
	"$(MONKEYDO)" bin/test.prg $(DEVICE) -t

test:                  ## Python- och Node-tester för analysverktygen
	python3 tools/test_trailanalysis.py
	python3 tools/test_trailsegments.py
	node tools/test_osmedit.js
