"use client";

import React, { useEffect, useState } from "react";

export interface UserRecord {
  user_id: string;
  name: string;
  role: string;
  team_id?: string;
}

const DEFAULT_USERS: UserRecord[] = [
  { user_id: "U-201", name: "Michael Turner", role: "production_supervisor", team_id: "TEAM-NE" },
  { user_id: "U-202", name: "Jessica Reed", role: "field_inspector", team_id: "TEAM-NE" },
  { user_id: "U-203", name: "Marcus Chen", role: "maintenance_lead", team_id: "TEAM-NE" },
  { user_id: "U-204", name: "David Kim", role: "compliance_officer", team_id: "TEAM-NE" },
  { user_id: "U-205", name: "Sarah Patel", role: "reservoir_engineer", team_id: "TEAM-NE" },
];

export function UserPicker({
  selectedUser,
  onUserChange,
}: {
  selectedUser: string;
  onUserChange: (userId: string) => void;
}) {
  const [users, setUsers] = useState<UserRecord[]>(DEFAULT_USERS);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/backend/users")
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load users");
        return res.json();
      })
      .then((data: UserRecord[]) => {
        if (!cancelled && Array.isArray(data) && data.length > 0) {
          setUsers(data);
        }
      })
      .catch(() => {
        // Fall back gracefully to DEFAULT_USERS
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <span className="font-medium text-foreground">Operator:</span>
      <select
        value={selectedUser}
        onChange={(e) => onUserChange(e.target.value)}
        className="rounded border border-border bg-background px-2 py-1 text-xs font-medium text-foreground focus:outline-none focus:ring-1 focus:ring-primary cursor-pointer"
        aria-label="Select Operator"
      >
        {users.map((u) => (
          <option key={u.user_id} value={u.user_id}>
            {u.name} ({u.role.replace("_", " ")})
          </option>
        ))}
      </select>
    </div>
  );
}
