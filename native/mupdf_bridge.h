#pragma once

#ifdef _WIN32
  #define AO_EXPORT __declspec(dllexport)
#else
  #define AO_EXPORT
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef void* ao_pdf_doc_handle;

// Basic DLL identity / diagnostics
AO_EXPORT const char* ao_pdf_backend_version(void);
AO_EXPORT const char* ao_pdf_last_error(void);
AO_EXPORT int ao_pdf_backend_is_stub(void);

// Phase 1 native render contract
AO_EXPORT int ao_pdf_open_document(const char* path_utf8, ao_pdf_doc_handle* out_doc);
AO_EXPORT void ao_pdf_close_document(ao_pdf_doc_handle doc);
AO_EXPORT int ao_pdf_get_page_count(ao_pdf_doc_handle doc);
AO_EXPORT int ao_pdf_get_page_size(ao_pdf_doc_handle doc, int page_index, double* out_width, double* out_height);
AO_EXPORT int ao_pdf_render_page_bgra(
    ao_pdf_doc_handle doc,
    int page_index,
    double zoom,
    unsigned char** out_pixels,
    int* out_width,
    int* out_height,
    int* out_stride
);
AO_EXPORT void ao_pdf_free_buffer(void* ptr);

#ifdef __cplusplus
}
#endif
