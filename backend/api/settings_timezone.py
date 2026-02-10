
# --- SYSTEM SETTINGS: TIMEZONE ---
@settings_bp.route('/settings/system/timezone', methods=['GET'])
@auth_required()
def get_system_timezone():
    """
    Get the configured system timezone.
    """
    from backend.utils.timezone_utils import get_display_timezone
    return jsonify({'timezone': get_display_timezone()}), 200
