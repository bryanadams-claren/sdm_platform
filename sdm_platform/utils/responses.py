"""
Standardized JSON response helpers for consistent API responses.

This module provides helper functions to ensure all JSON responses
follow the same structure across the application.
"""

from django.http import JsonResponse


def json_success(data=None, **kwargs):
    """
    Return a successful JSON response.

    Args:
        data: Optional dict of additional data to include
        **kwargs: Additional key-value pairs to include

    Returns:
        JsonResponse with {"success": True, ...}

    Examples:
        json_success()
        # {"success": True}

        json_success(message="Done")
        # {"success": True, "message": "Done"}

        json_success({"items": [1, 2, 3]}, count=3)
        # {"success": True, "items": [1, 2, 3], "count": 3}
    """
    response = {"success": True}
    if data:
        response.update(data)
    response.update(kwargs)
    return JsonResponse(response)


def json_error(message, status=400, **kwargs):
    """
    Return an error JSON response.

    Args:
        message: Error message string
        status: HTTP status code (default 400)
        **kwargs: Additional key-value pairs to include

    Returns:
        JsonResponse with {"success": False, "error": message, ...}

    Examples:
        json_error("Invalid input")
        # {"success": False, "error": "Invalid input"} with status 400

        json_error("Not found", status=404)
        # {"success": False, "error": "Not found"} with status 404

        json_error("Server error", status=500, details="Connection failed")
        # {"success": False, "error": "Server error", "details": "Connection failed"}
    """
    response = {"success": False, "error": message}
    response.update(kwargs)
    return JsonResponse(response, status=status)
