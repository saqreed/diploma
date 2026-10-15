/* Optional QA runner: Playwright installed in a separate local validation environment. */
const fs = require('node:fs/promises')
const path = require('node:path')
const scenario = process.argv[4] || 'flow'
const {run} = require(scenario === 'editor' ? './browser-editor.cjs' : scenario === 'review' ? './browser-review.cjs' : './browser-acceptance.cjs')

async function main() {
  const playwright = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
  const text = await fs.readFile(process.env.QA_ENV_FILE || '../.env', 'utf8')
  const env = Object.fromEntries(text.split(/\r?\n/).filter(line => line && !line.startsWith('#')).map(line => {
    const index = line.indexOf('='); return [line.slice(0, index), line.slice(index + 1)]
  }))
  const fixture = JSON.parse(await fs.readFile(process.env.QA_FIXTURE_CACHE, 'utf8'))
  const outputDirectory = process.env.QA_SCREENSHOTS
  await fs.mkdir(outputDirectory, {recursive: true})
  const report = await run({playwright, browserType: process.argv[2], executablePath: process.argv[3], env, outputDirectory, fixture})
  const reportName = process.env.QA_REPORT_NAME || 'browser-' + (process.argv[4] || process.argv[2]) + '.json'
  if (path.basename(reportName) !== reportName || !reportName.endsWith('.json')) throw new Error('Invalid QA report filename')
  await fs.writeFile(path.join('../diploma-docs/07_reports', reportName), JSON.stringify(report, null, 2))
  console.log(JSON.stringify(report))
}
main().catch(error => {
  const message = error.message.startsWith('Browser QA failed') ? error.message
    : 'Browser QA could not start: ' + (error.message.includes('spawn UNKNOWN') ? 'spawn UNKNOWN' : error.code || error.name)
  console.error(message)
  process.exitCode = 1
})
