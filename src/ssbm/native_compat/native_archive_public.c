#include "native_archive_root_api.h"

#include <baselib/archive.h>

#include <string.h>

// Explicit native host provider for HSD_ArchiveGetPublicAddress.
//
// Costume and stage archive tokens produced by
// pf_ssbm_native_archive_handle_require are startup-only handles, not
// parsed HSD_Archive images. Resolve public-symbol lookups against those
// handles through the startup-mapped source catalog, which exports the
// complete DAT public tables. Genuine parsed archives (stage DAT images,
// FigaTree motion-rate archives) execute the verbatim decomp lookup below,
// preserving NULL-on-miss and pointer-arithmetic behavior exactly.

void* HSD_ArchiveGetPublicAddress(HSD_Archive* archive, const char* symbols)
{
    u32 i;

    if (pf_ssbm_native_archive_stub_file(archive) != 0) {
        return pf_ssbm_native_archive_public_root_require(
            (void*) archive, symbols);
    }

    for (i = 0; i < archive->header.nb_public; i++) {
        int comparison =
            strcmp(archive->symbols + archive->public_info[i].symbol, symbols);

        if (comparison == 0) {
            // If both strings are equal, we've found the node
            return archive->data + archive->public_info[i].offset;
        }
    }

    return NULL;
}
