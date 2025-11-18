import mimetypes
from pathlib import Path

from django.http import FileResponse
from django.http import Http404
from django.shortcuts import get_object_or_404

from .models import Document


def document_download(request, pk):
    """
    Serve the uploaded document file for download.
    """
    document = get_object_or_404(Document, pk=pk)

    if not document.is_active:
        errmsg = "This document is no longer available."
        raise Http404(errmsg)

    if not document.file:
        errmsg = "No file found for this document."
        raise Http404(errmsg)

    file_path = document.file.path
    mime_type, _ = mimetypes.guess_type(file_path)

    return FileResponse(
        Path(file_path).open("rb"),
        as_attachment=True,
        filename=document.name,
        content_type=mime_type or "application/octet-stream",
    )
