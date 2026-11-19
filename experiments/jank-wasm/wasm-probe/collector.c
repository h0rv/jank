// Preprocess the collector's configuration without its public API header.
// This probes its explicit target guards, not a complete collector build.
#define GC_H
#include "gcconfig.h"
