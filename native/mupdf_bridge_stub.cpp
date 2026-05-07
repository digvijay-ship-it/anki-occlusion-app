#include "mupdf_bridge.h"

#include <algorithm>
#include <cstdlib>
#include <cstring>
#include <new>
#include <string>

extern "C" {
#include "mupdf/fitz/color.h"
#include "mupdf/fitz/context.h"
#include "mupdf/fitz/document.h"
#include "mupdf/fitz/geometry.h"
#include "mupdf/fitz/pixmap.h"
#include "mupdf/fitz/util.h"
#include "mupdf/fitz/version.h"
}

namespace {

struct AoPdfDocument {
    fz_context* ctx = nullptr;
    fz_document* doc = nullptr;
};

thread_local std::string g_last_error = "native MuPDF backend not initialized";
const std::string kVersion = std::string("anki_pdf_native MuPDF ") + FZ_VERSION;

void clear_last_error() {
    g_last_error.clear();
}

void set_last_error(const std::string& message) {
    g_last_error = message.empty() ? "unknown native PDF error" : message;
}

void set_last_error_from_ctx(fz_context* ctx, const char* prefix) {
    const char* msg = ctx ? fz_caught_message(ctx) : nullptr;
    if (msg && *msg) {
        set_last_error(std::string(prefix) + msg);
    } else {
        set_last_error(std::string(prefix) + "unknown MuPDF error");
    }
}

AoPdfDocument* doc_from_handle(ao_pdf_doc_handle handle) {
    auto* doc = reinterpret_cast<AoPdfDocument*>(handle);
    if (!doc || !doc->ctx || !doc->doc) {
        set_last_error("invalid native PDF document handle");
        return nullptr;
    }
    return doc;
}

bool compute_bgra_layout(int width, int height, size_t* out_stride, size_t* out_size) {
    if (!out_stride || !out_size || width <= 0 || height <= 0) {
        set_last_error("invalid render dimensions");
        return false;
    }
    const size_t width_sz = static_cast<size_t>(width);
    const size_t height_sz = static_cast<size_t>(height);
    if (width_sz > (static_cast<size_t>(-1) / 4u)) {
        set_last_error("render width too large");
        return false;
    }
    const size_t stride = width_sz * 4u;
    if (height_sz > 0 && stride > (static_cast<size_t>(-1) / height_sz)) {
        set_last_error("render buffer too large");
        return false;
    }
    *out_stride = stride;
    *out_size = stride * height_sz;
    return true;
}

} // namespace

extern "C" {

AO_EXPORT const char* ao_pdf_backend_version(void) {
    return kVersion.c_str();
}

AO_EXPORT const char* ao_pdf_last_error(void) {
    return g_last_error.c_str();
}

AO_EXPORT int ao_pdf_backend_is_stub(void) {
    return 0;
}

AO_EXPORT int ao_pdf_open_document(const char* path_utf8, ao_pdf_doc_handle* out_doc) {
    if (out_doc) {
        *out_doc = nullptr;
    }
    if (!path_utf8 || !*path_utf8 || !out_doc) {
        set_last_error("open_document requires a path and output handle");
        return 0;
    }

    fz_context* ctx = fz_new_context(nullptr, nullptr, FZ_STORE_DEFAULT);
    if (!ctx) {
        set_last_error("could not allocate MuPDF context");
        return 0;
    }

    fz_document* doc = nullptr;
    fz_var(doc);
    fz_register_document_handlers(ctx);

    fz_try(ctx) {
        doc = fz_open_document(ctx, path_utf8);
    }
    fz_catch(ctx) {
        set_last_error_from_ctx(ctx, "could not open PDF: ");
        if (doc) {
            fz_drop_document(ctx, doc);
        }
        fz_drop_context(ctx);
        return 0;
    }

    auto* handle = new (std::nothrow) AoPdfDocument();
    if (!handle) {
        set_last_error("could not allocate native document wrapper");
        fz_drop_document(ctx, doc);
        fz_drop_context(ctx);
        return 0;
    }

    handle->ctx = ctx;
    handle->doc = doc;
    *out_doc = reinterpret_cast<ao_pdf_doc_handle>(handle);
    clear_last_error();
    return 1;
}

AO_EXPORT void ao_pdf_close_document(ao_pdf_doc_handle doc) {
    auto* handle = reinterpret_cast<AoPdfDocument*>(doc);
    if (!handle) {
        return;
    }
    if (handle->doc && handle->ctx) {
        fz_drop_document(handle->ctx, handle->doc);
        handle->doc = nullptr;
    }
    if (handle->ctx) {
        fz_drop_context(handle->ctx);
        handle->ctx = nullptr;
    }
    delete handle;
}

AO_EXPORT int ao_pdf_get_page_count(ao_pdf_doc_handle doc) {
    auto* handle = doc_from_handle(doc);
    if (!handle) {
        return -1;
    }

    int count = -1;
    fz_try(handle->ctx) {
        count = fz_count_pages(handle->ctx, handle->doc);
    }
    fz_catch(handle->ctx) {
        set_last_error_from_ctx(handle->ctx, "could not count pages: ");
        return -1;
    }

    clear_last_error();
    return count;
}

AO_EXPORT int ao_pdf_get_page_size(
    ao_pdf_doc_handle doc,
    int page_index,
    double* out_width,
    double* out_height
) {
    if (out_width) {
        *out_width = 0.0;
    }
    if (out_height) {
        *out_height = 0.0;
    }

    auto* handle = doc_from_handle(doc);
    if (!handle || page_index < 0 || !out_width || !out_height) {
        if (page_index < 0) {
            set_last_error("page index must be non-negative");
        } else if (!out_width || !out_height) {
            set_last_error("page size outputs are required");
        }
        return 0;
    }

    fz_page* page = nullptr;
    fz_var(page);
    fz_rect bounds = fz_empty_rect;

    fz_try(handle->ctx) {
        page = fz_load_page(handle->ctx, handle->doc, page_index);
        bounds = fz_bound_page(handle->ctx, page);
    }
    fz_always(handle->ctx) {
        if (page) {
            fz_drop_page(handle->ctx, page);
        }
    }
    fz_catch(handle->ctx) {
        set_last_error_from_ctx(handle->ctx, "could not measure page: ");
        return 0;
    }

    *out_width = std::max(0.0, static_cast<double>(bounds.x1 - bounds.x0));
    *out_height = std::max(0.0, static_cast<double>(bounds.y1 - bounds.y0));
    clear_last_error();
    return 1;
}

AO_EXPORT int ao_pdf_render_page_bgra(
    ao_pdf_doc_handle doc,
    int page_index,
    double zoom,
    unsigned char** out_pixels,
    int* out_width,
    int* out_height,
    int* out_stride
) {
    if (out_pixels) {
        *out_pixels = nullptr;
    }
    if (out_width) {
        *out_width = 0;
    }
    if (out_height) {
        *out_height = 0;
    }
    if (out_stride) {
        *out_stride = 0;
    }

    auto* handle = doc_from_handle(doc);
    if (!handle || page_index < 0 || zoom <= 0.0 || !out_pixels || !out_width || !out_height || !out_stride) {
        if (page_index < 0) {
            set_last_error("page index must be non-negative");
        } else if (zoom <= 0.0) {
            set_last_error("zoom must be greater than zero");
        } else if (!out_pixels || !out_width || !out_height || !out_stride) {
            set_last_error("render outputs are required");
        }
        return 0;
    }

    fz_page* page = nullptr;
    fz_pixmap* pix = nullptr;
    unsigned char* buffer = nullptr;
    fz_var(page);
    fz_var(pix);
    fz_var(buffer);

    fz_try(handle->ctx) {
        page = fz_load_page(handle->ctx, handle->doc, page_index);
        pix = fz_new_pixmap_from_page(
            handle->ctx,
            page,
            fz_scale(static_cast<float>(zoom), static_cast<float>(zoom)),
            fz_device_bgr(handle->ctx),
            0
        );

        const int width = fz_pixmap_width(handle->ctx, pix);
        const int height = fz_pixmap_height(handle->ctx, pix);
        const int src_stride = fz_pixmap_stride(handle->ctx, pix);
        unsigned char* src = fz_pixmap_samples(handle->ctx, pix);

        size_t dst_stride = 0;
        size_t buffer_size = 0;
        if (!compute_bgra_layout(width, height, &dst_stride, &buffer_size)) {
            fz_throw(handle->ctx, FZ_ERROR_LIMIT, "%s", g_last_error.c_str());
        }

        buffer = static_cast<unsigned char*>(std::malloc(buffer_size));
        if (!buffer) {
            fz_throw(handle->ctx, FZ_ERROR_SYSTEM, "could not allocate render buffer");
        }

        for (int y = 0; y < height; ++y) {
            const unsigned char* src_row = src + static_cast<size_t>(y) * static_cast<size_t>(src_stride);
            unsigned char* dst_row = buffer + static_cast<size_t>(y) * dst_stride;
            for (int x = 0; x < width; ++x) {
                const size_t src_off = static_cast<size_t>(x) * 3u;
                const size_t dst_off = static_cast<size_t>(x) * 4u;
                dst_row[dst_off + 0] = src_row[src_off + 0];
                dst_row[dst_off + 1] = src_row[src_off + 1];
                dst_row[dst_off + 2] = src_row[src_off + 2];
                dst_row[dst_off + 3] = 255u;
            }
        }

        *out_pixels = buffer;
        *out_width = width;
        *out_height = height;
        *out_stride = static_cast<int>(dst_stride);
        buffer = nullptr;
    }
    fz_always(handle->ctx) {
        if (buffer) {
            std::free(buffer);
        }
        if (pix) {
            fz_drop_pixmap(handle->ctx, pix);
        }
        if (page) {
            fz_drop_page(handle->ctx, page);
        }
    }
    fz_catch(handle->ctx) {
        set_last_error_from_ctx(handle->ctx, "could not render page: ");
        return 0;
    }

    clear_last_error();
    return 1;
}

AO_EXPORT void ao_pdf_free_buffer(void* ptr) {
    if (ptr) {
        std::free(ptr);
    }
}

}
