import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Users, UserPlus, Trash2, Shield, FolderKanban } from 'lucide-react';
import { projectApi } from '../../api/project.api';
import styles from './people-access.module.css';

export default function PeopleAccessPage() {
  const queryClient = useQueryClient();
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [showAddModal, setShowAddModal] = useState(false);
  const [selectedUserId, setSelectedUserId] = useState('');
  const [selectedRole, setSelectedRole] = useState('CONTRIBUTOR');

  // 1. Fetch workspaces & projects
  const { data: workspaces } = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => projectApi.listWorkspaces(),
  });

  const workspaceId = workspaces?.[0]?.id;

  const { data: projects } = useQuery({
    queryKey: ['projects', workspaceId],
    queryFn: () => projectApi.listProjects(workspaceId),
    enabled: !!workspaceId,
  });

  const activeProjectId = selectedProjectId || projects?.[0]?.id;

  // 2. Fetch workspace members (to populate candidate dropdown in modal)
  const { data: workspaceMembers } = useQuery({
    queryKey: ['workspace-members', workspaceId],
    queryFn: () => projectApi.listWorkspaceMembers(workspaceId),
    enabled: !!workspaceId,
  });

  // 3. Fetch project members
  const { data: projectMembers, isLoading: membersLoading } = useQuery({
    queryKey: ['project-members', activeProjectId],
    queryFn: () => projectApi.listProjectMembers(activeProjectId),
    enabled: !!activeProjectId,
  });

  // Mutations
  const addMemberMutation = useMutation({
    mutationFn: ({ projectId, userId, role }) =>
      projectApi.addProjectMember(projectId, { user_id: userId, role }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project-members', activeProjectId] });
      setShowAddModal(false);
      setSelectedUserId('');
    },
  });

  const updateRoleMutation = useMutation({
    mutationFn: ({ projectId, userId, role }) =>
      projectApi.addProjectMember(projectId, { user_id: userId, role }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project-members', activeProjectId] });
    },
  });

  const removeMemberMutation = useMutation({
    mutationFn: ({ projectId, userId }) => projectApi.removeProjectMember(projectId, userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project-members', activeProjectId] });
    },
  });

  function getProjectRoleBadge(role = '') {
    const r = role.toUpperCase();
    if (r === 'LEAD') return styles.roleLead;
    if (r === 'REVIEWER') return styles.roleReviewer;
    return styles.roleContributor;
  }

  function getInitials(name = '') {
    const parts = name.split(' ');
    if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
    return name.slice(0, 2).toUpperCase();
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h2>People & Access Governance</h2>
          <p className={styles.subtitle}>
            Manage team members and configure role-based access control (Lead, Reviewer, Contributor)
            for projects and handover cases.
          </p>
        </div>
        <button
          type="button"
          className={styles.primaryBtn}
          onClick={() => setShowAddModal(true)}
          disabled={!activeProjectId}
        >
          <UserPlus size={16} />
          <span>Add Member</span>
        </button>
      </div>

      {/* Project Selector Bar */}
      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <h3>Project Team Roster</h3>
          {projects && projects.length > 0 && (
            <div className={styles.projectSelector}>
              <FolderKanban size={16} color="var(--color-text-secondary)" />
              <select
                className={styles.selectInput}
                value={activeProjectId || ''}
                onChange={(e) => setSelectedProjectId(e.target.value)}
              >
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        {/* Members Table */}
        <div className={styles.card}>
          {membersLoading ? (
            <div style={{ padding: 'var(--space-xl)', textAlign: 'center' }}>
              Loading members...
            </div>
          ) : !projectMembers || projectMembers.length === 0 ? (
            <div style={{ padding: 'var(--space-2xl)', textAlign: 'center' }}>
              <Users size={36} color="var(--color-text-muted)" style={{ marginBottom: '8px' }} />
              <p>No members assigned to this project yet.</p>
            </div>
          ) : (
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Team Member</th>
                  <th>Current Project Role</th>
                  <th>Change Role</th>
                  <th style={{ width: '80px', textAlign: 'center' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {projectMembers.map((member) => (
                  <tr key={member.id}>
                    <td>
                      <div className={styles.userCell}>
                        <div className={styles.avatar}>
                          {getInitials(member.user_display_name || member.user_email || 'U')}
                        </div>
                        <div>
                          <div className={styles.userName}>{member.user_display_name || '—'}</div>
                          <div className={styles.userEmail}>{member.user_email || '—'}</div>
                        </div>
                      </div>
                    </td>
                    <td>
                      <span className={`${styles.roleBadge} ${getProjectRoleBadge(member.role)}`}>
                        {member.role}
                      </span>
                    </td>
                    <td>
                      <select
                        className={styles.roleSelect}
                        value={member.role}
                        onChange={(e) =>
                          updateRoleMutation.mutate({
                            projectId: activeProjectId,
                            userId: member.user_id,
                            role: e.target.value,
                          })
                        }
                      >
                        <option value="LEAD">LEAD</option>
                        <option value="REVIEWER">REVIEWER</option>
                        <option value="CONTRIBUTOR">CONTRIBUTOR</option>
                      </select>
                    </td>
                    <td style={{ textAlign: 'center' }}>
                      <button
                        type="button"
                        className={styles.removeBtn}
                        title="Remove member from project"
                        onClick={() => {
                          if (
                            window.confirm(
                              `Remove ${member.user_display_name || member.user_email} from this project?`
                            )
                          ) {
                            removeMemberMutation.mutate({
                              projectId: activeProjectId,
                              userId: member.user_id,
                            });
                          }
                        }}
                      >
                        <Trash2 size={16} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Workspace Membership Overview */}
      {workspaceMembers && workspaceMembers.length > 0 && (
        <div className={styles.section} style={{ marginTop: 'var(--space-lg)' }}>
          <div className={styles.sectionHeader}>
            <h3>Workspace Organization Members</h3>
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-secondary)' }}>
              {workspaceMembers.length} active registered users
            </span>
          </div>

          <div className={styles.card}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>User</th>
                  <th>Workspace Organization Role</th>
                </tr>
              </thead>
              <tbody>
                {workspaceMembers.map((wm) => (
                  <tr key={wm.id}>
                    <td>
                      <div className={styles.userCell}>
                        <div className={styles.avatar}>
                          {getInitials(wm.user_display_name || wm.user_email || 'U')}
                        </div>
                        <div>
                          <div className={styles.userName}>{wm.user_display_name || '—'}</div>
                          <div className={styles.userEmail}>{wm.user_email}</div>
                        </div>
                      </div>
                    </td>
                    <td>
                      <span
                        className={`${styles.roleBadge} ${
                          wm.role === 'OWNER'
                            ? styles.roleOwner
                            : wm.role === 'ADMIN'
                            ? styles.roleAdmin
                            : styles.roleMember
                        }`}
                      >
                        {wm.role}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Add Member Modal */}
      {showAddModal && (
        <div className={styles.modalBackdrop}>
          <div className={styles.modalContent}>
            <h3>Add Member to Project</h3>
            <p style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-secondary)' }}>
              Select a workspace user to add to this project.
            </p>

            <div className={styles.formGroup}>
              <label>Select User</label>
              <select
                className={styles.input}
                value={selectedUserId}
                onChange={(e) => setSelectedUserId(e.target.value)}
              >
                <option value="">-- Choose a user --</option>
                {workspaceMembers?.map((u) => (
                  <option key={u.user_id} value={u.user_id}>
                    {u.user_display_name || u.user_email} ({u.user_email})
                  </option>
                ))}
              </select>
            </div>

            <div className={styles.formGroup}>
              <label>Project Role</label>
              <select
                className={styles.input}
                value={selectedRole}
                onChange={(e) => setSelectedRole(e.target.value)}
              >
                <option value="CONTRIBUTOR">CONTRIBUTOR</option>
                <option value="REVIEWER">REVIEWER</option>
                <option value="LEAD">LEAD</option>
              </select>
            </div>

            <div className={styles.modalActions}>
              <button
                type="button"
                className={styles.cancelBtn}
                onClick={() => setShowAddModal(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className={styles.primaryBtn}
                disabled={!selectedUserId}
                onClick={() => {
                  if (activeProjectId && selectedUserId) {
                    addMemberMutation.mutate({
                      projectId: activeProjectId,
                      userId: selectedUserId,
                      role: selectedRole,
                    });
                  }
                }}
              >
                Add Member
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
