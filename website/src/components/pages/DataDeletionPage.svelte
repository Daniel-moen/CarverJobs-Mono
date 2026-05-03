<script>
  import LegalDocPage from '../layout/LegalDocPage.svelte'
  import { supportEmail } from '../../config/site.js'
</script>

<LegalDocPage title="Delete your data">
  {#snippet children()}
    <p class="text-xs text-slate-500">How to request removal of your personal data from CARVER. Last updated: 3 May 2026.</p>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">1. Your right to deletion</h2>
      <p>
        Depending on applicable law (for example GDPR or similar rules), you may have the right to ask us to delete personal data we hold about you,
        subject to exceptions such as legal retention requirements.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">2. How to request deletion</h2>
      <p>Send an email from the address associated with your account to:</p>
      <p>
        <a class="text-cyan-400 underline hover:text-cyan-300" href="mailto:{supportEmail}?subject=Data%20deletion%20request">{supportEmail}</a>
      </p>
      <p class="text-slate-400">Use the subject line “Data deletion request” and include:</p>
      <ul class="list-inside list-disc space-y-1 text-slate-400">
        <li>The email address or username on your CARVER account.</li>
        <li>A brief confirmation that you want your account and associated personal data deleted.</li>
      </ul>
      <p>We may ask for reasonable information to verify you own the account before processing the request.</p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">3. What we delete</h2>
      <p>
        After verification, we will delete or anonymize your personal data in our active systems where we are not required to retain it.
        Backups may persist for a limited period before rotation; residual copies in logs may age out according to our retention schedule.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">4. What we may keep</h2>
      <p>
        We may retain certain records where the law requires (e.g. tax or fraud-prevention), or minimal data needed to enforce our terms and resolve disputes.
        Aggregated or de-identified data that does not identify you may also be retained.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">5. Timing</h2>
      <p>We aim to respond within 30 days. Complex requests may take longer; we will let you know if that applies.</p>
    </section>
  {/snippet}
</LegalDocPage>
