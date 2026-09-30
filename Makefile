# Builds and tests. Requires the Connect IQ SDK's bin folder in PATH for build and test-watch,
# or MONKEYC and MONKEYDO set to full paths.
MONKEYC  ?= monkeyc
MONKEYDO ?= monkeydo
DEVICE   ?= epix2
DEVKEY   ?= developer_key

.PHONY: build package build-test test test-watch

build:                 ## build the app to bin/mtbsurveyepixgen2.prg
	"$(MONKEYC)" -f monkey.jungle -d $(DEVICE) -o bin/mtbsurveyepixgen2.prg -y "$(DEVKEY)" -r

package:               ## build the package bin/mtbsurvey.iq for upload to the Connect IQ Store
	"$(MONKEYC)" -e -f monkey.jungle -o bin/mtbsurvey.iq -y "$(DEVKEY)" -r

build-test:            ## build the test variant with the unit tests in test/
	"$(MONKEYC)" -f monkey.jungle -d $(DEVICE) -o bin/test.prg -y "$(DEVKEY)" -t

test-watch: build-test ## run the unit tests in the simulator (start the simulator first)
	"$(MONKEYDO)" bin/test.prg $(DEVICE) -t

test:                  ## Python and Node tests for the analysis tools
	python3 tools/test_trailanalysis.py
	python3 tools/test_trailsegments.py
	python3 tools/test_devicecheck.py
	node tools/test_osmedit.js
