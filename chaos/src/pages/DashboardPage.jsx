import React, { useEffect, useState } from 'react';
import {
  Plus,
  UploadCloud,
  FlaskConical,
  Folder,
  AlertTriangle,
  Microscope,
  ShieldCheck,
  Layers
} from 'lucide-react';

import BlurText from '../components/BlurText';
import CountUp from '../components/CountUp';
import Tooltip from '../components/Tooltip';
import SpotlightCard from '../components/SpotlightCard';
import { listProjects, listRuns, getReport } from '../api';

export default function DashboardPage({ setCurrentView }) {
  const [recentProjects, setRecentProjects] = useState([]);
  const [runs, setRuns] = useState([]);

  useEffect(() => {
    let cancelled = false;

    Promise.all([listProjects(), listRuns(100)])
      .then(([p, r]) => {
        if (cancelled) return;

        const projectList = p.projects || [];
        const runList = r.runs || [];

        setRuns(runList);

        Promise.all(
          projectList.slice(0, 4).map(async (x) => {
            const report = await getReport(x.id).catch(() => null);
            const score = report?.resilience_score_pct;

            return {
              name: x.name,
              env: x.status || 'UPLOADED',
              status: x.status || 'UPLOADED',
              resilience: typeof score === 'number' ? score : 0,
              tested: typeof score === 'number',
              statusType:
                score == null
                  ? 'neutral'
                  : score >= 80
                    ? 'stable'
                    : score >= 60
                      ? 'degraded'
                      : 'injecting',
              id: x.id
            };
          })
        ).then((items) => {
          if (!cancelled) {
            setRecentProjects(items);
          }
        });
      })
      .catch(() => {
        if (!cancelled) {
          setRecentProjects([]);
          setRuns([]);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const failedRuns = runs.filter((r) =>
    ['APPLICATION_FAILURE', 'CRASHED', 'WEAK_HANDLING'].includes(r.outcome)
  ).length;

  const passedRuns = runs.filter((r) =>
    ['PASSED', 'RECOVERED'].includes(r.outcome)
  ).length;

  // Resilience is a rate over *completed* experiment outcomes only. Runs
  // still in flight (RUNNING) or otherwise unresolved have no verdict yet,
  // so counting them in the denominator understates resilience for any
  // project with in-progress runs.
  const completedRuns = passedRuns + failedRuns;
  const resilience =
    completedRuns > 0
      ? Math.round((passedRuns / completedRuns) * 1000) / 10
      : 0;

  /*
   * Build the Activity Feed from real experiment runs.
   * This replaces the undefined `activities` variable.
   */
  const activities = runs
    .slice()
    .sort((a, b) => {
      const dateA = new Date(a.started_at || a.created_at || 0).getTime();
      const dateB = new Date(b.started_at || b.created_at || 0).getTime();

      return dateB - dateA;
    })
    .slice(0, 5)
    .map((run) => {
      const outcome = run.outcome || run.status || 'UNKNOWN';

      let color = '#818cf8';

      if (['PASSED', 'RECOVERED'].includes(outcome)) {
        color = '#10b981';
      } else if (
        ['APPLICATION_FAILURE', 'CRASHED', 'WEAK_HANDLING'].includes(outcome)
      ) {
        color = '#ef4444';
      } else if (outcome === 'RUNNING') {
        color = '#f59e0b';
      }

      const experimentName =
        run.experiment_name ||
        run.experiment_id ||
        'Chaos experiment';

      const projectName =
        run.project_name ||
        run.project_id ||
        'Project';

      const rawTime =
        run.started_at ||
        run.created_at ||
        run.completed_at ||
        null;

      let time = 'Unknown time';

      if (rawTime) {
        const date = new Date(rawTime);

        if (!Number.isNaN(date.getTime())) {
          time = date.toLocaleString();
        }
      }

      return {
        title: `${experimentName} — ${outcome}`,
        detail: `${projectName} • Experiment run`,
        time,
        color
      };
    });

  return (
    <div
      style={{
        padding: '32px',
        color: '#fff',
        zIndex: 1,
        position: 'relative'
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '32px'
        }}
      >
        <div>
          <BlurText
            as="h1"
            text="System Overview"
            animateBy="letters"
            delay={20}
            style={{
              fontSize: '28px',
              fontWeight: '700',
              letterSpacing: '-0.5px',
              marginBottom: '4px'
            }}
          />

          <p
            style={{
              color: '#94a3b8',
              fontSize: '13px',
              margin: 0
            }}
          >
            Monitor chaos experiments and system resilience.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '12px' }}>
          <Tooltip
            position="bottom"
            title="New project"
            text="Upload a project zip to analyze it and start generating chaos experiments"
          >
            <button
              className="btn-secondary"
              onClick={() => setCurrentView('import')}
            >
              <Plus size={16} />
              New Project
            </button>
          </Tooltip>

          <Tooltip
            position="bottom"
            title="Import a project"
            text="Upload a project as a zip file"
          >
            <button
              className="btn-secondary"
              onClick={() => setCurrentView('import')}
            >
              <UploadCloud size={16} />
              Import
            </button>
          </Tooltip>

          <Tooltip
            position="bottom"
            title="Chaos Lab"
            text="Run fault-injection experiments against a project in an isolated sandbox"
          >
            <button
              className="btn-primary"
              onClick={() => setCurrentView('chaos-lab')}
            >
              <FlaskConical size={16} />
              Chaos Lab
            </button>
          </Tooltip>
        </div>
      </div>

      {/* 4 Stat Cards */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
          gap: '20px',
          marginBottom: '32px'
        }}
      >
        {/* Card 1 */}
        <Tooltip
          position="top"
          title="Active Projects"
          text="Projects you've uploaded and are currently analyzing or testing"
          style={{ width: '100%' }}
        >
          <SpotlightCard
            spotlightColor="rgba(99, 102, 241, 0.25)"
            style={{
              padding: '20px',
              width: '100%',
              boxSizing: 'border-box'
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: '16px'
              }}
            >
              <span
                style={{
                  fontSize: '11px',
                  fontWeight: '600',
                  color: '#94a3b8',
                  letterSpacing: '0.5px'
                }}
              >
                ACTIVE PROJECTS
              </span>

              <Folder size={18} color="#94a3b8" />
            </div>

            <div
              style={{
                display: 'flex',
                alignItems: 'baseline',
                gap: '10px'
              }}
            >
              <span
                style={{
                  fontSize: '32px',
                  fontWeight: '800',
                  letterSpacing: '-1px'
                }}
              >
                <CountUp to={recentProjects.length} duration={1.5} />
              </span>

              <span
                style={{
                  fontSize: '12px',
                  color: '#94a3b8',
                  fontWeight: '600'
                }}
              >
                {failedRuns} findings
              </span>
            </div>
          </SpotlightCard>
        </Tooltip>

        {/* Card 2 */}
        <Tooltip
          position="top"
          title="Running Injections"
          text="Currently running chaos experiments"
          style={{ width: '100%' }}
        >
          <SpotlightCard
            spotlightColor="rgba(239, 68, 68, 0.2)"
            style={{
              padding: '20px',
              width: '100%',
              boxSizing: 'border-box'
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: '16px'
              }}
            >
              <span
                style={{
                  fontSize: '11px',
                  fontWeight: '600',
                  color: '#94a3b8',
                  letterSpacing: '0.5px'
                }}
              >
                RUNNING INJECTIONS
              </span>

              <AlertTriangle size={18} color="#ef4444" />
            </div>

            <div
              style={{
                display: 'flex',
                alignItems: 'baseline',
                gap: '10px'
              }}
            >
              <span
                style={{
                  fontSize: '32px',
                  fontWeight: '800',
                  letterSpacing: '-1px'
                }}
              >
                <CountUp
                  to={runs.filter((r) => r.status === 'RUNNING').length}
                  duration={1.5}
                />
              </span>

              <span
                style={{
                  fontSize: '11px',
                  color: '#94a3b8'
                }}
              >
                active runs
              </span>
            </div>
          </SpotlightCard>
        </Tooltip>

        {/* Card 3 */}
        <Tooltip
          position="top"
          title="Total Experiments"
          text="Total chaos experiment runs recorded by the backend"
          style={{ width: '100%' }}
        >
          <SpotlightCard
            spotlightColor="rgba(167, 139, 250, 0.2)"
            style={{
              padding: '20px',
              width: '100%',
              boxSizing: 'border-box'
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: '16px'
              }}
            >
              <span
                style={{
                  fontSize: '11px',
                  fontWeight: '600',
                  color: '#94a3b8',
                  letterSpacing: '0.5px'
                }}
              >
                TOTAL EXPERIMENTS
              </span>

              <Microscope size={18} color="#a78bfa" />
            </div>

            <div
              style={{
                display: 'flex',
                alignItems: 'baseline',
                gap: '10px'
              }}
            >
              <span
                style={{
                  fontSize: '32px',
                  fontWeight: '800',
                  letterSpacing: '-1px'
                }}
              >
                <CountUp
                  to={runs.length}
                  separator=","
                  duration={2}
                />
              </span>

              <span
                style={{
                  fontSize: '11px',
                  color: '#94a3b8',
                  fontWeight: '600'
                }}
              >
                {failedRuns} failures
              </span>
            </div>
          </SpotlightCard>
        </Tooltip>

        {/* Card 4 */}
        <Tooltip
          position="top"
          title="Global Resilience Score"
          text="Calculated from recorded experiment outcomes"
          style={{ width: '100%' }}
        >
          <SpotlightCard
            spotlightColor="rgba(16, 185, 129, 0.2)"
            style={{
              padding: '20px',
              width: '100%',
              boxSizing: 'border-box'
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: '16px'
              }}
            >
              <span
                style={{
                  fontSize: '11px',
                  fontWeight: '600',
                  color: '#94a3b8',
                  letterSpacing: '0.5px'
                }}
              >
                GLOBAL RESILIENCE
              </span>

              <ShieldCheck size={18} color="#10b981" />
            </div>

            <div
              style={{
                display: 'flex',
                alignItems: 'baseline',
                gap: '10px'
              }}
            >
              <span
                style={{
                  fontSize: '32px',
                  fontWeight: '800',
                  letterSpacing: '-1px'
                }}
              >
                <CountUp to={resilience} duration={2} />%
              </span>

              <span
                style={{
                  fontSize: '11px',
                  color: '#94a3b8'
                }}
              >
                Score
              </span>
            </div>
          </SpotlightCard>
        </Tooltip>
      </div>

      {/* Main Grid Content */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '2fr 1fr',
          gap: '24px'
        }}
      >
        {/* Recent Projects Table */}
        <SpotlightCard
          spotlightColor="rgba(99, 102, 241, 0.2)"
          style={{ padding: '24px' }}
        >
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: '20px'
            }}
          >
            <h3
              style={{
                fontSize: '16px',
                fontWeight: '600',
                margin: 0
              }}
            >
              Recent Projects
            </h3>

            <Tooltip
              position="left"
              title="All Projects"
              text="Browse complete project catalog"
            >
              <button
                onClick={() => setCurrentView('projects')}
                style={{
                  background: 'none',
                  border: 'none',
                  color: '#818cf8',
                  fontSize: '12px',
                  cursor: 'pointer',
                  fontWeight: '500'
                }}
              >
                View All
              </button>
            </Tooltip>
          </div>

          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              textAlign: 'left'
            }}
          >
            <thead>
              <tr
                style={{
                  borderBottom:
                    '1px solid rgba(255, 255, 255, 0.08)',
                  color: '#64748b',
                  fontSize: '10px',
                  textTransform: 'uppercase',
                  letterSpacing: '0.5px'
                }}
              >
                <th style={{ paddingBottom: '12px' }}>
                  PROJECT NAME
                </th>

                <th style={{ paddingBottom: '12px' }}>
                  STATUS
                </th>

                <th style={{ paddingBottom: '12px' }}>
                  RESILIENCE
                </th>
              </tr>
            </thead>

            <tbody>
              {recentProjects.map((project, idx) => (
                <tr
                  key={project.id || idx}
                  onClick={() => setCurrentView('projects')}
                  className="interactive-table-row"
                  style={{
                    borderBottom:
                      idx < recentProjects.length - 1
                        ? '1px solid rgba(255, 255, 255, 0.04)'
                        : 'none',
                    cursor: 'pointer'
                  }}
                >
                  <td style={{ padding: '14px 12px' }}>
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '12px',
                        minWidth: 0
                      }}
                    >
                      <div
                        style={{
                          width: '32px',
                          height: '32px',
                          borderRadius: '6px',
                          background:
                            'rgba(255, 255, 255, 0.05)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          flexShrink: 0
                        }}
                      >
                        <Layers
                          size={16}
                          color="#94a3b8"
                        />
                      </div>

                      <div style={{ minWidth: 0, flex: 1, overflow: 'hidden' }}>
                        <div
                          style={{
                            fontSize: '13px',
                            fontWeight: '600',
                            color: '#f3f4f6',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap'
                          }}
                          title={project.name}
                        >
                          {project.name}
                        </div>

                        <div
                          style={{
                            fontSize: '11px',
                            color: '#64748b',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap'
                          }}
                        >
                          {project.env}
                        </div>
                      </div>
                    </div>
                  </td>

                  <td style={{ padding: '14px 12px' }}>
                    <Tooltip
                      position="top"
                      title={project.tested ? `Resilience score: ${project.resilience}%` : 'Not tested yet'}
                      text={
                        !project.tested
                          ? 'No experiments have been run against this project yet'
                          : project.statusType === 'stable'
                            ? 'Handled the fault scenarios tested against it cleanly'
                            : project.statusType === 'degraded'
                              ? 'Handled some tested fault scenarios; others need attention'
                              : 'Several tested fault scenarios exposed real failures'
                      }
                    >
                      <span
                        className={`badge badge-${project.statusType}`}
                      >
                        ● {project.tested ? project.status : 'Untested'}
                      </span>
                    </Tooltip>
                  </td>

                  <td style={{ padding: '14px 12px' }}>
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '12px'
                      }}
                    >
                      <div
                        style={{
                          flex: 1,
                          height: '6px',
                          background:
                            'rgba(255, 255, 255, 0.08)',
                          borderRadius: '3px',
                          overflow: 'hidden'
                        }}
                      >
                        <div
                          style={{
                            width: `${project.resilience}%`,
                            height: '100%',
                            background:
                              project.resilience > 90
                                ? '#10b981'
                                : project.resilience > 80
                                  ? '#f59e0b'
                                  : '#ef4444',
                            borderRadius: '3px'
                          }}
                        />
                      </div>

                      <span
                        style={{
                          fontSize: '12px',
                          fontWeight: '600',
                          minWidth: '32px'
                        }}
                      >
                        <CountUp
                          to={project.resilience}
                          duration={1.2}
                        />
                        %
                      </span>
                    </div>
                  </td>
                </tr>
              ))}

              {recentProjects.length === 0 && (
                <tr>
                  <td
                    colSpan="3"
                    style={{
                      padding: '30px',
                      textAlign: 'center',
                      color: '#64748b',
                      fontSize: '12px'
                    }}
                  >
                    No projects available yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </SpotlightCard>

        {/* Activity Feed */}
        <SpotlightCard
          spotlightColor="rgba(99, 102, 241, 0.2)"
          style={{
            padding: '24px',
            display: 'flex',
            flexDirection: 'column'
          }}
        >
          <h3
            style={{
              fontSize: '16px',
              fontWeight: '600',
              marginBottom: '20px',
              margin: 0
            }}
          >
            Activity Feed
          </h3>

          <div
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              gap: '16px',
              marginTop: '16px'
            }}
          >
            {activities.length > 0 ? (
              activities.map((act, idx) => (
                <Tooltip
                  key={idx}
                  position="left"
                  title={act.title}
                  text={`${act.detail} • Occurred ${act.time}`}
                  style={{ width: '100%' }}
                >
                  <div
                    className="activity-feed-item"
                    style={{
                      display: 'flex',
                      gap: '14px',
                      alignItems: 'flex-start',
                      width: '100%',
                      minWidth: 0
                    }}
                  >
                    <span
                      className="feed-indicator"
                      style={{
                        width: '8px',
                        height: '8px',
                        borderRadius: '50%',
                        background: act.color,
                        marginTop: '6px',
                        flexShrink: 0,
                        boxShadow: `0 0 8px ${act.color}`,
                        transition:
                          'transform 0.2s ease, filter 0.2s ease'
                      }}
                    />

                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'flex-start',
                          marginBottom: '2px',
                          gap: '8px',
                          flexWrap: 'wrap'
                        }}
                      >
                        <span
                          style={{
                            fontSize: '13px',
                            fontWeight: '600',
                            color: '#e2e8f0',
                            overflowWrap: 'anywhere',
                            wordBreak: 'break-word',
                            flex: 1,
                            minWidth: 0
                          }}
                        >
                          {act.title}
                        </span>

                        <span
                          style={{
                            fontSize: '10px',
                            color: '#64748b',
                            flexShrink: 0
                          }}
                        >
                          {act.time}
                        </span>
                      </div>

                      <div
                        style={{
                          fontSize: '11px',
                          color: '#94a3b8',
                          lineHeight: '1.4',
                          overflowWrap: 'anywhere',
                          wordBreak: 'break-word'
                        }}
                      >
                        {act.detail}
                      </div>
                    </div>
                  </div>
                </Tooltip>
              ))
            ) : (
              <div
                style={{
                  padding: '24px 8px',
                  textAlign: 'center',
                  color: '#64748b',
                  fontSize: '12px'
                }}
              >
                No experiment activity yet.
              </div>
            )}
          </div>

          <Tooltip
            position="top"
            title="Activity Logs Audit Trail"
            text="Open the recorded chaos events and telemetry entries"
          >
            <button
              className="btn-secondary"
              onClick={() => setCurrentView('logs')}
              style={{
                marginTop: '20px',
                width: '100%',
                justifyContent: 'center',
                fontSize: '12px'
              }}
            >
              Load More
            </button>
          </Tooltip>
        </SpotlightCard>
      </div>
    </div>
  );
}