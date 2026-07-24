//! Terminal dashboard for Hestia.
//!
//! Polls the daemon's `GET /api/dashboard` endpoint every second and
//! renders the same data the web view shows: society identity, activity
//! stats, plugin trust, witness chain feed, tool histogram.
//!
//! Press `q`, `Esc`, or `Ctrl+C` to quit.

use std::io::{self, Stdout};
use std::time::{Duration, Instant};

use anyhow::{Context, Result};
use crossterm::{
    event::{self, DisableMouseCapture, EnableMouseCapture, Event, KeyCode, KeyModifiers},
    execute,
    terminal::{EnterAlternateScreen, LeaveAlternateScreen, disable_raw_mode, enable_raw_mode},
};
use ratatui::{
    Frame, Terminal,
    backend::CrosstermBackend,
    layout::{Alignment, Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style, Stylize},
    symbols::border,
    text::{Line, Span},
    widgets::{Block, Borders, Cell, Gauge, Paragraph, Row, Table, Wrap},
};

use crate::server::{DashboardSnapshot, RecentEntry, TrustView};

const ACCENT: Color = Color::Rgb(255, 139, 61); // hearth-fire
const ACCENT_DIM: Color = Color::Rgb(160, 90, 40);
const FG: Color = Color::Rgb(230, 232, 238);
const FG_DIM: Color = Color::Rgb(154, 160, 172);
const FG_FAINT: Color = Color::Rgb(91, 96, 104);
const SUCCESS: Color = Color::Rgb(74, 222, 128);
const FAILURE: Color = Color::Rgb(248, 113, 113);
const BG_ELEV: Color = Color::Rgb(21, 23, 28);

type Term = Terminal<CrosstermBackend<Stdout>>;

pub fn run(endpoint: &str) -> Result<()> {
    let mut terminal = setup_terminal()?;
    let result = run_loop(&mut terminal, endpoint);
    restore_terminal(&mut terminal)?;
    result
}

fn setup_terminal() -> Result<Term> {
    enable_raw_mode().context("enabling raw mode")?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen, EnableMouseCapture)?;
    let backend = CrosstermBackend::new(stdout);
    Terminal::new(backend).context("creating terminal")
}

fn restore_terminal(terminal: &mut Term) -> Result<()> {
    disable_raw_mode().ok();
    execute!(
        terminal.backend_mut(),
        LeaveAlternateScreen,
        DisableMouseCapture
    )
    .ok();
    terminal.show_cursor().ok();
    Ok(())
}

struct AppState {
    snapshot: Option<DashboardSnapshot>,
    last_error: Option<String>,
    last_fetch: Instant,
    fetch_count: u64,
}

fn run_loop(terminal: &mut Term, endpoint: &str) -> Result<()> {
    let url = if endpoint.ends_with("/api/dashboard") {
        endpoint.to_string()
    } else {
        format!("{}/api/dashboard", endpoint.trim_end_matches('/'))
    };
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()?;
    let mut state = AppState {
        snapshot: None,
        last_error: None,
        last_fetch: Instant::now() - Duration::from_secs(60),
        fetch_count: 0,
    };
    let refresh = Duration::from_millis(1000);

    loop {
        if state.last_fetch.elapsed() >= refresh {
            match fetch(&client, &url) {
                Ok(snap) => {
                    state.snapshot = Some(snap);
                    state.last_error = None;
                }
                Err(e) => state.last_error = Some(format!("{e}")),
            }
            state.last_fetch = Instant::now();
            state.fetch_count += 1;
        }

        terminal.draw(|f| draw(f, &state, &url))?;

        if event::poll(Duration::from_millis(150))? {
            if let Event::Key(key) = event::read()? {
                if key.modifiers.contains(KeyModifiers::CONTROL) && key.code == KeyCode::Char('c') {
                    break;
                }
                match key.code {
                    KeyCode::Char('q') | KeyCode::Esc => break,
                    _ => {}
                }
            }
        }
    }
    Ok(())
}

fn fetch(client: &reqwest::blocking::Client, url: &str) -> Result<DashboardSnapshot> {
    let res = client
        .get(url)
        .send()
        .with_context(|| format!("GET {url}"))?;
    let snap = res
        .json::<DashboardSnapshot>()
        .context("decoding snapshot")?;
    Ok(snap)
}

fn draw(f: &mut Frame, state: &AppState, url: &str) {
    let area = f.area();
    let outer = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3), // header
            Constraint::Length(5), // stat row
            Constraint::Min(0),    // body
            Constraint::Length(1), // footer
        ])
        .split(area);

    draw_header(f, outer[0], state);
    draw_stats(f, outer[1], state);
    draw_body(f, outer[2], state);
    draw_footer(f, outer[3], state, url);
}

fn draw_header(f: &mut Frame, area: Rect, state: &AppState) {
    let status = if state.last_error.is_some() {
        Span::styled("offline", Style::default().fg(FAILURE))
    } else if state.snapshot.is_some() {
        Span::styled("● live", Style::default().fg(SUCCESS))
    } else {
        Span::styled("connecting…", Style::default().fg(FG_DIM))
    };

    let title = Line::from(vec![
        Span::styled("◉ ", Style::default().fg(ACCENT).bold()),
        Span::styled("Hestia", Style::default().fg(FG).bold()),
        Span::raw("  "),
        Span::styled("local-first Web4 trust layer", Style::default().fg(FG_DIM)),
    ]);
    let right = Line::from(vec![
        status,
        Span::raw("  "),
        Span::styled(
            format!("ticks {}", state.fetch_count),
            Style::default().fg(FG_FAINT),
        ),
    ])
    .alignment(Alignment::Right);

    let block = Block::default()
        .borders(Borders::BOTTOM)
        .border_set(border::PLAIN)
        .border_style(Style::default().fg(FG_FAINT));
    let inner = block.inner(area);
    f.render_widget(block, area);

    let cols = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(60), Constraint::Percentage(40)])
        .split(inner);
    f.render_widget(Paragraph::new(title).alignment(Alignment::Left), cols[0]);
    f.render_widget(Paragraph::new(right), cols[1]);
}

fn draw_stats(f: &mut Frame, area: Rect, state: &AppState) {
    let cols = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Ratio(1, 4),
            Constraint::Ratio(1, 4),
            Constraint::Ratio(1, 4),
            Constraint::Ratio(1, 4),
        ])
        .split(area);

    let (chain, actions, rate, hour) = match &state.snapshot {
        Some(s) => (
            format!("{}", s.society.chain_length),
            format!("{}", s.stats.total_actions),
            if s.stats.total_actions == 0 {
                "—".to_string()
            } else {
                format!("{:.1}%", s.stats.success_rate * 100.0)
            },
            format!("{}", s.stats.actions_last_hour),
        ),
        None => ("—".into(), "—".into(), "—".into(), "—".into()),
    };

    draw_stat(f, cols[0], "WITNESS CHAIN", &chain, ACCENT);
    draw_stat(f, cols[1], "ACTIONS", &actions, FG);
    draw_stat(f, cols[2], "SUCCESS RATE", &rate, SUCCESS);
    draw_stat(f, cols[3], "LAST HOUR", &hour, FG);
}

fn draw_stat(f: &mut Frame, area: Rect, label: &str, value: &str, value_color: Color) {
    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(Style::default().fg(FG_FAINT))
        .style(Style::default().bg(BG_ELEV));
    let inner = block.inner(area);
    f.render_widget(block, area);

    let text = vec![
        Line::from(Span::styled(
            label,
            Style::default().fg(FG_DIM).add_modifier(Modifier::DIM),
        )),
        Line::from(""),
        Line::from(Span::styled(value, Style::default().fg(value_color).bold())),
    ];
    f.render_widget(
        Paragraph::new(text).alignment(Alignment::Left),
        Rect {
            x: inner.x + 1,
            y: inner.y,
            width: inner.width.saturating_sub(2),
            height: inner.height,
        },
    );
}

fn draw_body(f: &mut Frame, area: Rect, state: &AppState) {
    let cols = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(40), Constraint::Percentage(60)])
        .split(area);

    draw_trust(f, cols[0], state);
    let right = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Percentage(60), Constraint::Percentage(40)])
        .split(cols[1]);
    draw_feed(f, right[0], state);
    draw_histogram(f, right[1], state);
}

fn draw_trust(f: &mut Frame, area: Rect, state: &AppState) {
    let block = section_block("Plugin Trust");
    let inner = block.inner(area);
    f.render_widget(block, area);

    let trust: &[TrustView] = state
        .snapshot
        .as_ref()
        .map(|s| s.trust.as_slice())
        .unwrap_or(&[]);
    if trust.is_empty() {
        f.render_widget(
            Paragraph::new("No plugins recorded yet.")
                .style(Style::default().fg(FG_FAINT))
                .alignment(Alignment::Center),
            Rect {
                x: inner.x,
                y: inner.y + inner.height / 2,
                width: inner.width,
                height: 1,
            },
        );
        return;
    }

    let per_item = 6u16;
    let mut y = inner.y;
    for t in trust.iter().take((inner.height / per_item) as usize) {
        let area_t = Rect {
            x: inner.x + 1,
            y,
            width: inner.width.saturating_sub(2),
            height: per_item.min(inner.height - (y - inner.y)),
        };
        if area_t.height < 3 {
            break;
        }
        let head = Line::from(vec![
            Span::styled(&t.plugin_id, Style::default().fg(FG).bold()),
            Span::raw("  "),
            Span::styled(
                format!("[{}]", &t.level),
                Style::default().fg(ACCENT).add_modifier(Modifier::DIM),
            ),
            Span::raw("  "),
            Span::styled(
                format!("actions {}", t.action_count),
                Style::default().fg(FG_DIM),
            ),
            Span::raw("  "),
            Span::styled(
                if t.action_count == 0 {
                    "—".to_string()
                } else {
                    format!("ok {:.0}%", t.success_rate * 100.0)
                },
                Style::default().fg(SUCCESS),
            ),
        ]);
        f.render_widget(
            Paragraph::new(head),
            Rect {
                x: area_t.x,
                y: area_t.y,
                width: area_t.width,
                height: 1,
            },
        );
        // Canonical unmeasured-handling: None = zero observations on that
        // dimension — render "unmeas" rather than a fabricated score.
        draw_gauge(
            f,
            area_t.x,
            area_t.y + 1,
            area_t.width,
            "Talent  ",
            t.t3_talent,
        );
        draw_gauge(
            f,
            area_t.x,
            area_t.y + 2,
            area_t.width,
            "Training",
            t.t3_training,
        );
        draw_gauge(
            f,
            area_t.x,
            area_t.y + 3,
            area_t.width,
            "Temper  ",
            t.t3_temperament,
        );
        draw_gauge(
            f,
            area_t.x,
            area_t.y + 4,
            area_t.width,
            "Veracity",
            t.v3_veracity,
        );

        y += per_item;
        if y >= inner.y + inner.height {
            break;
        }
    }
}

fn draw_gauge(f: &mut Frame, x: u16, y: u16, w: u16, label: &str, value: Option<f64>) {
    if w < 20 {
        return;
    }
    let label_w = 10;
    let val_w = 6;
    let bar_w = w.saturating_sub(label_w + val_w);
    let label_area = Rect {
        x,
        y,
        width: label_w,
        height: 1,
    };
    let bar_area = Rect {
        x: x + label_w,
        y,
        width: bar_w,
        height: 1,
    };
    let val_area = Rect {
        x: x + label_w + bar_w,
        y,
        width: val_w,
        height: 1,
    };

    f.render_widget(
        Paragraph::new(Span::styled(label, Style::default().fg(FG_DIM))),
        label_area,
    );

    // Unmeasured dimension (zero observations): empty bar + "unmeas", never a
    // fabricated 0.5 score.
    let Some(value) = value else {
        f.render_widget(
            Paragraph::new(Span::styled("unmeas ", Style::default().fg(FG_DIM)))
                .alignment(Alignment::Right),
            val_area,
        );
        return;
    };

    let pct = (value.clamp(0.0, 1.0) * 100.0) as u16;
    let gauge = Gauge::default()
        .gauge_style(Style::default().fg(ACCENT).bg(BG_ELEV))
        .percent(pct)
        .label("");
    f.render_widget(gauge, bar_area);

    f.render_widget(
        Paragraph::new(Span::styled(
            format!("{:>5.2} ", value),
            Style::default().fg(FG),
        ))
        .alignment(Alignment::Right),
        val_area,
    );
}

fn draw_feed(f: &mut Frame, area: Rect, state: &AppState) {
    let block = section_block("Witness Chain — live");
    let inner = block.inner(area);
    f.render_widget(block, area);

    let empty: Vec<RecentEntry> = Vec::new();
    let entries = state.snapshot.as_ref().map(|s| &s.recent).unwrap_or(&empty);
    if entries.is_empty() {
        f.render_widget(
            Paragraph::new("Waiting for the first chain entry…")
                .style(Style::default().fg(FG_FAINT))
                .alignment(Alignment::Center),
            Rect {
                x: inner.x,
                y: inner.y + inner.height / 2,
                width: inner.width,
                height: 1,
            },
        );
        return;
    }
    let rows: Vec<Row> = entries
        .iter()
        .take(inner.height as usize)
        .map(|e| {
            let pos =
                Cell::from(format!("#{}", e.chain_position)).style(Style::default().fg(FG_FAINT));
            let typ_style = if e.event_type == "outcome" {
                Style::default().fg(FG)
            } else {
                Style::default().fg(FG_DIM)
            };
            let typ = Cell::from(e.event_type.clone()).style(typ_style);
            let tool = e.tool_name.clone().unwrap_or_default();
            let tool_cell =
                Cell::from(tool).style(Style::default().fg(ACCENT).add_modifier(Modifier::BOLD));
            let detail = e.target.clone().unwrap_or_else(|| {
                if e.event_type == "session_started" {
                    e.plugin_id.clone().unwrap_or_default()
                } else {
                    String::new()
                }
            });
            let detail_cell = Cell::from(detail).style(Style::default().fg(FG_DIM));
            let status = match e.success {
                Some(true) => Cell::from("ok").style(Style::default().fg(SUCCESS)),
                Some(false) => Cell::from("FAIL")
                    .style(Style::default().fg(FAILURE).add_modifier(Modifier::BOLD)),
                None => Cell::from(""),
            };
            let hash_short: String = e.hash.chars().take(10).collect();
            let hash_cell =
                Cell::from(format!("{}…", hash_short)).style(Style::default().fg(FG_FAINT));
            Row::new(vec![pos, typ, tool_cell, detail_cell, status, hash_cell])
        })
        .collect();

    let widths = [
        Constraint::Length(6),
        Constraint::Length(16),
        Constraint::Length(12),
        Constraint::Min(10),
        Constraint::Length(5),
        Constraint::Length(12),
    ];
    let table = Table::new(rows, widths).column_spacing(1);
    f.render_widget(table, inner);
}

fn draw_histogram(f: &mut Frame, area: Rect, state: &AppState) {
    let block = section_block("Tool Histogram");
    let inner = block.inner(area);
    f.render_widget(block, area);

    let by_tool = match &state.snapshot {
        Some(s) => &s.stats.by_tool,
        None => return,
    };
    if by_tool.is_empty() {
        f.render_widget(
            Paragraph::new("No tool calls yet.")
                .style(Style::default().fg(FG_FAINT))
                .alignment(Alignment::Center),
            Rect {
                x: inner.x,
                y: inner.y + inner.height / 2,
                width: inner.width,
                height: 1,
            },
        );
        return;
    }
    let max = by_tool[0].1.max(1);
    let mut y = inner.y;
    for (name, count) in by_tool.iter().take(inner.height as usize) {
        let label_w = 12u16;
        let count_w = 6u16;
        let bar_w = inner.width.saturating_sub(label_w + count_w + 2);
        if bar_w == 0 || inner.width < 24 {
            break;
        }
        let label_area = Rect {
            x: inner.x + 1,
            y,
            width: label_w,
            height: 1,
        };
        let bar_area = Rect {
            x: inner.x + 1 + label_w,
            y,
            width: bar_w,
            height: 1,
        };
        let count_area = Rect {
            x: inner.x + 1 + label_w + bar_w,
            y,
            width: count_w,
            height: 1,
        };
        f.render_widget(
            Paragraph::new(Span::styled(name.clone(), Style::default().fg(FG_DIM))),
            label_area,
        );
        let pct = ((*count as f64 / max as f64) * 100.0) as u16;
        f.render_widget(
            Gauge::default()
                .gauge_style(Style::default().fg(ACCENT_DIM).bg(BG_ELEV))
                .percent(pct)
                .label(""),
            bar_area,
        );
        f.render_widget(
            Paragraph::new(format!("{:>5}", count))
                .style(Style::default().fg(FG))
                .alignment(Alignment::Right),
            count_area,
        );
        y += 1;
        if y >= inner.y + inner.height {
            break;
        }
    }
}

fn draw_footer(f: &mut Frame, area: Rect, state: &AppState, url: &str) {
    let lct = state
        .snapshot
        .as_ref()
        .map(|s| s.society.sovereign_lct.clone())
        .unwrap_or_else(|| "—".into());
    let err = state.last_error.clone().unwrap_or_default();
    let line = Line::from(vec![
        Span::styled(format!(" {}", lct), Style::default().fg(FG_FAINT)),
        Span::raw("   "),
        Span::styled(format!("→ {}", url), Style::default().fg(FG_FAINT)),
        Span::raw("   "),
        Span::styled(
            if err.is_empty() {
                "q to quit"
            } else {
                err.as_str()
            },
            Style::default().fg(if err.is_empty() { FG_FAINT } else { FAILURE }),
        ),
    ]);
    f.render_widget(
        Paragraph::new(line)
            .wrap(Wrap { trim: false })
            .style(Style::default().fg(FG_DIM)),
        area,
    );
}

fn section_block(title: &str) -> Block<'_> {
    Block::default()
        .borders(Borders::ALL)
        .border_style(Style::default().fg(FG_FAINT))
        .title(Span::styled(
            format!(" {} ", title),
            Style::default().fg(FG_DIM).add_modifier(Modifier::DIM),
        ))
}
