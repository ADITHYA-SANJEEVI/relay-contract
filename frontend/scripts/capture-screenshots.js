import puppeteer from 'puppeteer';
import { preview } from 'vite';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const SCREENSHOT_DIR = process.env.RELAY_SCREENSHOT_DIR
  ? path.resolve(process.env.RELAY_SCREENSHOT_DIR)
  : path.resolve(__dirname, '../../docs/ui/screenshots');

if (!fs.existsSync(SCREENSHOT_DIR)) {
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
}

async function run() {
  console.log('Starting Vite preview server...');
  const server = await preview({
    root: path.resolve(__dirname, '..'),
    preview: { port: 4173 }
  });

  console.log('Launching Puppeteer browser...');
  const browser = await puppeteer.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });

  try {
    const page = await browser.newPage();

    // Matrix of viewports and states
    const captures = [
      {
        name: '01_job_detail_1440x900_scenario_a.png',
        url: 'http://localhost:4173/board/jobs/11111111-1111-4111-8111-111111111111?partition=0',
        width: 1440,
        height: 900,
      },
      {
        name: '02_job_detail_1366x768_scenario_b_deadline_passed.png',
        url: 'http://localhost:4173/board/jobs/11111111-1111-4111-8111-111111111111?partition=1',
        width: 1366,
        height: 768,
      },
      {
        name: '03_job_detail_1280x800_running_with_failed_partition.png',
        url: 'http://localhost:4173/board/jobs/33333333-3333-4333-8333-333333333333?partition=3',
        width: 1280,
        height: 800,
      },
      {
        name: '04_job_detail_1024x768_failed_partial_results.png',
        url: 'http://localhost:4173/board/jobs/22222222-2222-4222-8222-222222222222?partition=0',
        width: 1024,
        height: 768,
      },
      {
        name: '05_job_detail_768x1024_tablet.png',
        url: 'http://localhost:4173/board/jobs/11111111-1111-4111-8111-111111111111?partition=0',
        width: 768,
        height: 1024,
      },
      {
        name: '06_activity_events_chronology.png',
        url: 'http://localhost:4173/board/jobs/11111111-1111-4111-8111-111111111111?tab=activity',
        width: 1440,
        height: 900,
      },
      {
        name: '07_results_verified_manifests.png',
        url: 'http://localhost:4173/board/jobs/11111111-1111-4111-8111-111111111111?tab=results',
        width: 1440,
        height: 900,
        action: async (page) => {
          const loadBtn = await page.$('button.btn-primary');
          if (loadBtn) {
            await loadBtn.click();
            await new Promise((res) => setTimeout(res, 800));
          }
        }
      },
      {
        name: '08_failure_lab_recorded_evidence.png',
        url: 'http://localhost:4173/board/lab',
        width: 1440,
        height: 900,
      },
      {
        name: '09_workers_fleet_observation.png',
        url: 'http://localhost:4173/board/workers',
        width: 1440,
        height: 900,
      },
      {
        name: '10_overview_open_job.png',
        url: 'http://localhost:4173/board',
        width: 1440,
        height: 900,
      },
      {
        name: '11_scenario_e_no_accepted_result.png',
        url: 'http://localhost:4173/board/jobs/11111111-1111-4111-8111-111111111111?partition=2',
        width: 1440,
        height: 900,
        scenario: 'SCENARIO_E_NO_ACCEPTED_RESULT',
      },
      {
        name: '12_scenario_f_integrity_failure.png',
        url: 'http://localhost:4173/board/jobs/11111111-1111-4111-8111-111111111111?partition=3',
        width: 1440,
        height: 900,
        scenario: 'SCENARIO_F_INTEGRITY_FAILURE',
      },
      {
        name: '13_scenario_g_disconnected_state.png',
        url: 'http://localhost:4173/board/jobs/11111111-1111-4111-8111-111111111111',
        width: 1440,
        height: 900,
        scenario: 'SCENARIO_G_DISCONNECTED',
      },
      {
        name: '14_scenario_h_missing_capability_gap.png',
        url: 'http://localhost:4173/board/jobs/11111111-1111-4111-8111-111111111111?partition=0',
        width: 1440,
        height: 900,
        scenario: 'SCENARIO_H_CAPABILITY_GAP',
      }
    ];

    for (const cap of captures) {
      console.log(`Capturing ${cap.name} (${cap.width}x${cap.height})...`);
      await page.setViewport({ width: cap.width, height: cap.height });
      await page.goto(cap.url, { waitUntil: 'networkidle0' });
      await new Promise((res) => setTimeout(res, 500));

      if (cap.scenario) {
        const select = await page.$('#scenario-select');
        if (select) {
          await page.select('#scenario-select', cap.scenario);
          await new Promise((res) => setTimeout(res, 600));
        }
      }

      if (cap.action) {
        await cap.action(page);
      }

      const filePath = path.join(SCREENSHOT_DIR, cap.name);
      await page.screenshot({ path: filePath });
      console.log(`Saved screenshot: ${filePath}`);
    }

    console.log('All screenshots captured successfully!');
  } finally {
    if (browser) await browser.close();
    server.httpServer.close();
  }
}

run().catch((err) => {
  console.error('Screenshot script failed:', err);
  process.exit(1);
});
