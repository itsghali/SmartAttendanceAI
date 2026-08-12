from sqlalchemy import insert, select

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.role import Permission, Role, role_permissions

ROLE_NAMES = [
    "super_admin",
    "admin",
    "hr_manager",
    "supervisor",
    "employee",
    "auditor",
]

PERMISSIONS = {
    "users:read": "View user accounts",
    "users:write": "Create/update user accounts",
    "users:delete": "Deactivate/delete user accounts",
    "roles:manage": "Assign roles and manage permissions",
    "devices:read:own": "View own registered devices",
    "devices:manage:own": "Revoke own registered devices",
    "devices:manage:all": "Revoke any user's registered devices",
    "sessions:read:own": "View own active sessions",
    "sessions:manage:own": "Revoke own active sessions",
    "sessions:manage:all": "Revoke any user's active sessions",
    "audit_logs:read": "View audit logs",
    "geofences:read": "View geofence zones",
    "geofences:write": "Create/update geofence zones",
    # Deliberately separate from attendance:read:all, which supervisor also
    # holds — this permission gates the geofence-exit exceptions/history
    # screens, and supervisor is explicitly excluded from those (see the
    # "Geofence-Exit Alerts + Structured Attendance History" design doc).
    "geofence_events:read": (
        "View geofence-exit alerts, per-employee attendance history, and face-verification attempts"
    ),
    "attendance:record:own": "Check in/out and start/end break for yourself",
    "attendance:read:own": "View your own attendance history",
    "attendance:read:all": "View any employee's attendance records",
    "attendance:correct": "Create manual/backfill entries and correct existing attendance records",
    "problem_reports:create:own": "Report a problem to HR",
    "problem_reports:read:all": "View employee-submitted problem reports",
    "problem_reports:resolve": "Mark a problem report as resolved",
}

ROLE_PERMISSIONS: dict[str, list[str]] = {
    "super_admin": list(PERMISSIONS.keys()),
    "admin": [
        "users:read",
        "users:write",
        "users:delete",
        "devices:manage:all",
        "sessions:manage:all",
        "audit_logs:read",
        "geofences:read",
        "geofences:write",
        "geofence_events:read",
        "attendance:read:all",
        "attendance:correct",
        "problem_reports:read:all",
        "problem_reports:resolve",
    ],
    "hr_manager": [
        "users:read",
        "users:write",
        "users:delete",
        "audit_logs:read",
        "geofences:read",
        "geofences:write",
        "geofence_events:read",
        "attendance:read:all",
        "attendance:correct",
        "problem_reports:read:all",
        "problem_reports:resolve",
    ],
    "supervisor": ["users:read", "attendance:read:all", "attendance:correct"],
    "employee": [
        "devices:read:own",
        "devices:manage:own",
        "sessions:read:own",
        "sessions:manage:own",
        "attendance:record:own",
        "attendance:read:own",
        "problem_reports:create:own",
    ],
    "auditor": ["users:read", "audit_logs:read", "geofences:read", "attendance:read:all"],
}


async def seed_rbac(session: AsyncSession) -> None:
    """Idempotent: creates the 6 roles, baseline permissions, and their mappings.

    Uses Core inserts against the association table directly instead of ORM
    relationship assignment, since assigning a bidirectional collection on an
    object fetched without eager-loading forces a lazy load, which async
    SQLAlchemy can't do outside a greenlet context.
    """
    existing_permissions = {
        p.code: p for p in (await session.execute(select(Permission))).scalars().all()
    }
    for code, description in PERMISSIONS.items():
        if code not in existing_permissions:
            permission = Permission(code=code, description=description)
            session.add(permission)
            existing_permissions[code] = permission
    await session.flush()

    existing_roles = {r.name: r for r in (await session.execute(select(Role))).scalars().all()}
    for name in ROLE_NAMES:
        if name not in existing_roles:
            role = Role(name=name)
            session.add(role)
            existing_roles[name] = role
    await session.flush()

    existing_pairs = set(
        (await session.execute(select(role_permissions))).all()
    )
    rows_to_insert = []
    for role_name, permission_codes in ROLE_PERMISSIONS.items():
        role_id = existing_roles[role_name].id
        for code in permission_codes:
            permission_id = existing_permissions[code].id
            if (role_id, permission_id) not in existing_pairs:
                rows_to_insert.append({"role_id": role_id, "permission_id": permission_id})

    if rows_to_insert:
        await session.execute(insert(role_permissions), rows_to_insert)

    await session.commit()
