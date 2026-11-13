import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Compass,
  X,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
  ExternalLink,
  ShieldCheck,
  Users,
  GitBranch,
  FileStack,
  CheckSquare,
  Eye,
  ScrollText,
  Sparkles,
  RefreshCw,
  Lock,
  Layers,
  ChevronRight,
  HelpCircle,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import styles from './judge-guide-modal.module.css';

const PERSONAS = [
  {
    name: 'Maya Sharma',
    email: 'maya.sharma@example.test',
    role: 'Project Lead / Workspace Owner',
    badge: 'Lead',
    description: 'Creates cases, connects repos, tracks overall handover health & drift.',
    color: '#3b82f6',
  },
  {
    name: 'Kabir Singh',
    email: 'kabir.singh@example.test',
    role: 'Technical Reviewer',
    badge: 'Reviewer',
    description: 'Inspects claims, clarifies discrepancies, edits, and approves version snapshots.',
    color: '#8b5cf6',
  },
  {
    name: 'Aisha Khan',
    email: 'aisha.khan@example.test',
    role: 'Designated Successor',
    badge: 'Successor',
    description: 'Onboards via 4 Operational Pillars with restricted evidence redaction & pack sign-off.',
    color: '#10b981',
  },
  {
    name: 'Arjun Patel',
    email: 'arjun.patel@example.test',
    role: 'Departing Engineer',
    badge: 'Departing',
    description: 'Auth & payments architect; primary source of reconstructed project knowledge.',
    color: 'var(--color-warning)',
  },
];

const ACTS = [
  {
    number: 1,
    title: 'Lead Scope & Source Freshness',
    persona: 'Maya Sharma (Project Lead)',
    personaEmail: 'maya.sharma@example.test',
    summary: 'Explore live project health metrics, connected repositories, and trigger freshness verification.',
    steps: [
      'View the real-time Dashboard overview metrics (3 active projects, 4 transfer packs, live sync status).',
      'Navigate to Sources (/sources) to inspect connected repositories (Atlas Platform, Pydantic, Zulip).',
      'Click "Check Freshness" to observe real-time drift detection and SHA-level evidence verification.',
    ],
    targetPath: '/sources',
    actionLabel: 'Go to Sources & Drift Check',
    icon: GitBranch,
  },
  {
    number: 2,
    title: 'Evidence Grounding & Conflict Resolution',
    persona: 'Maya Sharma or Kabir Singh',
    personaEmail: 'maya.sharma@example.test',
    summary: 'Inspect reconstructed Transfer Packs, bi-directional citations, and conflicting/unknown claims.',
    steps: [
      'Open Handover Cases (/cases) and click "Arjun Patel - Atlas Platform Handover".',
      'Click into the "Authentication API & Multi-Tenancy" Transfer Pack.',
      'Notice the 14 Grounded Claims: every claim cites specific PRs (#101), commits (abc0002), or documents.',
      'Inspect the CONFLICTING Claim ("Architecture Decision: Microservices vs Monolith"): HandoffScope flagged contradicting Confluence ADR vs live commit implementation.',
      'Inspect the UNKNOWN Claim ("Production latency benchmarks"): HandoffScope explicitly flags missing knowledge instead of hallucinating!',
    ],
    targetPath: '/cases',
    actionLabel: 'Inspect Handover Case & Claims',
    icon: FileStack,
  },
  {
    number: 3,
    title: 'Targeted Question Reconstruction',
    persona: 'Maya Sharma or Arjun Patel',
    personaEmail: 'maya.sharma@example.test',
    summary: 'Autonomous gap detection triggers targeted questions to capture tacit knowledge before departure.',
    steps: [
      'Navigate to Questions (/questions).',
      'Inspect the questions generated autonomously from unverified runbooks and ambiguous configuration flags.',
      'Review answers captured from the departing developer and how they promote into permanent verified claims.',
    ],
    targetPath: '/questions',
    actionLabel: 'Explore Targeted Questions',
    icon: HelpCircle,
  },
  {
    number: 4,
    title: 'Review Queue & Immutable Version Snapshot',
    persona: 'Kabir Singh (Reviewer)',
    personaEmail: 'kabir.singh@example.test',
    summary: 'Human-in-the-loop review workflow, inline claim editing, and frozen version snapshot sign-off.',
    steps: [
      'Switch persona to Kabir Singh (Reviewer) using the 1-click button below.',
      'Go to the Review Queue (/review).',
      'Examine claims awaiting review. Try clicking "Edit & Accept" or "Needs Clarification".',
      'Observe Version Snapshot v1: frozen state with cryptographic hash integrity ensuring zero post-signoff tampering.',
    ],
    targetPath: '/review',
    actionLabel: 'Open Review Queue',
    icon: CheckSquare,
  },
  {
    number: 5,
    title: 'Successor Onboarding & Evidence Redaction',
    persona: 'Aisha Khan (Successor)',
    personaEmail: 'aisha.khan@example.test',
    summary: 'Successor operational onboarding across 4 pillars with enterprise privacy redaction.',
    steps: [
      'Switch persona to Aisha Khan (Successor) using the 1-click button below.',
      'Navigate to Successor View (/successor).',
      'Explore the 4 Operational Pillars: Architecture, Operations, Dependencies, Incidents.',
      'Notice the Security Redaction Banner: "Restricted Evidence Withheld" — confidential employee comments and raw PR diffs are withheld per RBAC while operational knowledge remains accessible.',
      'Test acknowledging or accepting responsibility for transfer packs.',
    ],
    targetPath: '/successor',
    actionLabel: 'Experience Successor View',
    icon: Eye,
  },
];

export function JudgeGuideModal({ isOpen, onClose }) {
  const [activeTab, setActiveTab] = useState('acts'); // 'acts' | 'personas' | 'fast-track' | 'architecture'
  const [currentActIndex, setCurrentActIndex] = useState(0);
  const [switching, setSwitching] = useState(false);
  const [switchError, setSwitchError] = useState(null);
  const [dontShowAgain, setDontShowAgain] = useState(false);
  const { user, login } = useAuth();
  const navigate = useNavigate();

  const handleDismiss = () => {
    if (dontShowAgain) {
      try {
        localStorage.setItem('handoffscope_guide_dismissed', 'true');
      } catch {
        // Ignore storage write issues
      }
    }
    if (onClose) onClose();
  };

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        handleDismiss();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, dontShowAgain, onClose]);

  if (!isOpen) return null;

  const handleSwitchPersona = async (email) => {
    try {
      setSwitching(true);
      setSwitchError(null);
      await login(email, 'handoffscope-dev-2026');
    } catch (err) {
      console.error('Failed to switch persona:', err);
      setSwitchError(err?.data?.detail || err?.message || 'Failed to switch persona');
    } finally {
      setSwitching(false);
    }
  };

  const currentAct = ACTS[currentActIndex] || ACTS[0];

  return (
    <div className={styles.overlay} onClick={handleDismiss} role="presentation">
      <div
        className={styles.modal}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="judge-guide-title"
      >
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerTitleWrap}>
            <div className={styles.headerIconBadge}>
              <Sparkles size={20} className={styles.headerSparkle} />
            </div>
            <div>
              <div className={styles.tagline}>Workspace Quickstart • Interactive Product Tour</div>
              <h2 id="judge-guide-title" className={styles.title}>HandoffScope Guide</h2>
            </div>
          </div>
          <button type="button" className={styles.closeBtn} onClick={handleDismiss} title="Close Guide" aria-label="Close Guide">
            <X size={20} />
          </button>
        </div>

        {/* Navigation Tabs */}
        <div className={styles.navTabs}>
          <button
            type="button"
            className={`${styles.tabBtn} ${activeTab === 'acts' ? styles.tabBtnActive : ''}`}
            onClick={() => setActiveTab('acts')}
          >
            <Compass size={16} />
            <span>Interactive 5-Act Walkthrough</span>
          </button>
          <button
            type="button"
            className={`${styles.tabBtn} ${activeTab === 'personas' ? styles.tabBtnActive : ''}`}
            onClick={() => setActiveTab('personas')}
          >
            <Users size={16} />
            <span>1-Click Persona Switcher</span>
          </button>
          <button
            type="button"
            className={`${styles.tabBtn} ${activeTab === 'fast-track' ? styles.tabBtnActive : ''}`}
            onClick={() => setActiveTab('fast-track')}
          >
            <Layers size={16} />
            <span>3-Min Fast Track</span>
          </button>
          <button
            type="button"
            className={`${styles.tabBtn} ${activeTab === 'architecture' ? styles.tabBtnActive : ''}`}
            onClick={() => setActiveTab('architecture')}
          >
            <ShieldCheck size={16} />
            <span>Zero-Hallucination Guarantees</span>
          </button>
        </div>

        {/* Body Content */}
        <div className={styles.body}>
          {/* TAB 1: 5-ACT WALKTHROUGH */}
          {activeTab === 'acts' && (
            <div className={styles.actsContainer}>
              {/* Act Selector Pills */}
              <div className={styles.actSelector}>
                {ACTS.map((act, idx) => (
                  <button
                    type="button"
                    key={act.number}
                    className={`${styles.actPill} ${idx === currentActIndex ? styles.actPillActive : ''}`}
                    onClick={() => setCurrentActIndex(idx)}
                  >
                    <span className={styles.actNumber}>Act {act.number}</span>
                    <span className={styles.actPillTitle}>{act.title}</span>
                  </button>
                ))}
              </div>

              {/* Current Act Detail Card */}
              <div className={styles.actCard}>
                <div className={styles.actCardHeader}>
                  <div className={styles.actCardHeaderLeft}>
                    <span className={styles.actBadge}>Act {currentAct.number} of 5</span>
                    <h3 className={styles.actTitle}>{currentAct.title}</h3>
                  </div>
                  <div className={styles.actPersonaBox}>
                    <span className={styles.actPersonaLabel}>Recommended Persona:</span>
                    <span className={styles.actPersonaValue}>{currentAct.persona}</span>
                    {user?.email !== currentAct.personaEmail && (
                      <button
                        type="button"
                        className={styles.switchPersonaQuickBtn}
                        onClick={() => handleSwitchPersona(currentAct.personaEmail)}
                        disabled={switching}
                      >
                        {switching ? 'Switching…' : 'Switch to this persona'}
                      </button>
                    )}
                  </div>
                </div>

                <p className={styles.actSummary}>{currentAct.summary}</p>

                <div className={styles.stepsTitle}>Recommended Walkthrough Steps:</div>
                <ol className={styles.stepsList}>
                  {currentAct.steps.map((step, idx) => (
                    <li key={idx} className={styles.stepItem}>
                      <span className={styles.stepBullet}>{idx + 1}</span>
                      <span className={styles.stepText}>{step}</span>
                    </li>
                  ))}
                </ol>

                <div className={styles.actActions}>
                  <button
                    type="button"
                    className={styles.navigateBtn}
                    onClick={() => {
                      navigate(currentAct.targetPath);
                      handleDismiss();
                    }}
                  >
                    <span>{currentAct.actionLabel}</span>
                    <ArrowRight size={16} />
                  </button>

                  <div className={styles.actStepNav}>
                    <button
                      type="button"
                      className={styles.stepNavBtn}
                      disabled={currentActIndex === 0}
                      onClick={() => setCurrentActIndex((i) => i - 1)}
                    >
                      Previous Act
                    </button>
                    <button
                      type="button"
                      className={styles.stepNavBtn}
                      disabled={currentActIndex === ACTS.length - 1}
                      onClick={() => setCurrentActIndex((i) => i + 1)}
                    >
                      Next Act
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* TAB 2: PERSONA SWITCHER */}
          {activeTab === 'personas' && (
            <div className={styles.personaTab}>
              <p className={styles.tabIntro}>
                HandoffScope implements strict Role-Based Access Control (RBAC). Switch personas below in 1-click
                to experience different visibility levels, from Lead to Reviewer and Successor:
              </p>

              {switchError && <div className={styles.switchError}>{switchError}</div>}

              <div className={styles.personaGrid}>
                {PERSONAS.map((p) => {
                  const isCurrent = user?.email === p.email;
                  return (
                    <div
                      key={p.email}
                      className={`${styles.personaCard} ${isCurrent ? styles.personaCardCurrent : ''}`}
                    >
                      <div className={styles.personaCardHeader}>
                        <div>
                          <div className={styles.personaName}>{p.name}</div>
                          <div className={styles.personaRoleText}>{p.role}</div>
                        </div>
                        <span
                          className={styles.personaTag}
                          style={{ borderColor: p.color, color: p.color }}
                        >
                          {p.badge}
                        </span>
                      </div>
                      <p className={styles.personaDesc}>{p.description}</p>
                      <div className={styles.personaFooter}>
                        <span className={styles.personaEmail}>{p.email}</span>
                        {isCurrent ? (
                          <span className={styles.activeUserBadge}>
                            <CheckCircle2 size={14} /> Active Persona
                          </span>
                        ) : (
                          <button
                            type="button"
                            className={styles.personaSelectBtn}
                            onClick={() => handleSwitchPersona(p.email)}
                            disabled={switching}
                          >
                            {switching ? 'Switching…' : 'Switch to Persona'}
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* TAB 3: 3-MINUTE FAST TRACK */}
          {activeTab === 'fast-track' && (
            <div className={styles.fastTrackTab}>
              <div className={styles.fastTrackIntro}>
                <strong>Short on time?</strong> Follow this 3-minute guided tour to explore the core handover capabilities:
              </div>

              <div className={styles.fastTrackGrid}>
                <div
                  className={styles.fastTrackCard}
                  role="button"
                  tabIndex={0}
                  onClick={() => { navigate('/cases'); handleDismiss(); }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      navigate('/cases');
                      handleDismiss();
                    }
                  }}
                >
                  <div className={styles.fastTrackNumber}>01</div>
                  <div className={styles.fastTrackContent}>
                    <h4>Bi-Directional Evidence Grounding</h4>
                    <p>Go to Handover Cases → Arjun Patel Handover → Auth API Pack. Every claim links to exact git commits and PRs.</p>
                  </div>
                  <ChevronRight size={18} className={styles.fastTrackArrow} />
                </div>

                <div
                  className={styles.fastTrackCard}
                  role="button"
                  tabIndex={0}
                  onClick={() => { navigate('/cases'); handleDismiss(); }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      navigate('/cases');
                      handleDismiss();
                    }
                  }}
                >
                  <div className={styles.fastTrackNumber}>02</div>
                  <div className={styles.fastTrackContent}>
                    <h4>Contradiction & Unknown Detection</h4>
                    <p>Look at Claim #3 (ADR vs PR conflict flagged in amber) and Claim #5 (explicit UNKNOWN for missing latency tests).</p>
                  </div>
                  <ChevronRight size={18} className={styles.fastTrackArrow} />
                </div>

                <div
                  className={styles.fastTrackCard}
                  role="button"
                  tabIndex={0}
                  onClick={() => { navigate('/review'); handleDismiss(); }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      navigate('/review');
                      handleDismiss();
                    }
                  }}
                >
                  <div className={styles.fastTrackNumber}>03</div>
                  <div className={styles.fastTrackContent}>
                    <h4>Review Queue & Snapshot Versioning</h4>
                    <p>Visit /review to see human-in-the-loop editing, claim clarification, and cryptographic v1 snapshot freeze.</p>
                  </div>
                  <ChevronRight size={18} className={styles.fastTrackArrow} />
                </div>

                <div
                  className={styles.fastTrackCard}
                  role="button"
                  tabIndex={0}
                  onClick={() => { navigate('/successor'); handleDismiss(); }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      navigate('/successor');
                      handleDismiss();
                    }
                  }}
                >
                  <div className={styles.fastTrackNumber}>04</div>
                  <div className={styles.fastTrackContent}>
                    <h4>Successor View & Redaction Policy</h4>
                    <p>Visit /successor as Aisha Khan. Check the 4 Operational Pillars and the Restricted Evidence withholding banner.</p>
                  </div>
                  <ChevronRight size={18} className={styles.fastTrackArrow} />
                </div>
              </div>
            </div>
          )}

          {/* TAB 4: ARCHITECTURE & ZERO HALLUCINATION */}
          {activeTab === 'architecture' && (
            <div className={styles.archTab}>
              <div className={styles.archGrid}>
                <div className={styles.archCard}>
                  <div className={styles.archIcon}><ShieldCheck size={20} /></div>
                  <h4>Zero Hallucination Guarantee</h4>
                  <p>Claims are never generated ex-nihilo. Every single factual statement is cited against verifiable Git commits, PRs, issues, or documents stored in Neon PostgreSQL.</p>
                </div>

                <div className={styles.archCard}>
                  <div className={styles.archIcon}><AlertTriangle size={20} /></div>
                  <h4>Explicit Unknown & Conflict States</h4>
                  <p>When engineering evidence is contradictory (e.g. Confluence says monolith, Git says microservice), HandoffScope flags it as CONFLICTING. When documentation is missing, it explicitly marks it UNKNOWN.</p>
                </div>

                <div className={styles.archCard}>
                  <div className={styles.archIcon}><Lock size={20} /></div>
                  <h4>Role-Based Selective Redaction</h4>
                  <p>Successors receive concise, verified operational handovers without leaking confidential salary notes, personal departure comments, or sensitive security configs.</p>
                </div>

                <div className={styles.archCard}>
                  <div className={styles.archIcon}><ScrollText size={20} /></div>
                  <h4>Tamper-Evident Audit Trail</h4>
                  <p>Every review, edit, approval, and responsibility acceptance is recorded in a structured audit log (/audit) with actor timestamps and previous/new state diffs.</p>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className={styles.footer}>
          <label className={styles.dontShowLabel}>
            <input
              type="checkbox"
              checked={dontShowAgain}
              onChange={(e) => setDontShowAgain(e.target.checked)}
            />
            <span>Don&apos;t show this walkthrough automatically on login</span>
          </label>

          <div className={styles.footerButtons}>
            <button type="button" className={styles.dismissBtn} onClick={handleDismiss}>
              Close &amp; Explore Workspace
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
