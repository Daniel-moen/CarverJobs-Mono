<script>
  import LegalDocPage from '../layout/LegalDocPage.svelte'
  import { supportEmail } from '../../config/site.js'
</script>

<LegalDocPage title="Privacy Policy">
  {#snippet children()}
    <p class="text-xs text-slate-500">Last updated: 3 May 2026. Privacy and data-rights requests: <a class="text-cyan-500/90 underline hover:text-cyan-400" href="mailto:{supportEmail}">{supportEmail}</a>.</p>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">1. Who we are</h2>
      <p>
        CARVER (“we”, “us”) operates this website and related services for superyacht crew job discovery and
        applications. Contact: <a class="text-cyan-400 underline hover:text-cyan-300" href="mailto:{supportEmail}">{supportEmail}</a>.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">2. Information we collect</h2>
      <p>We may collect:</p>
      <ul class="list-inside list-disc space-y-1 text-slate-400">
        <li>Account details (e.g. email, username, authentication identifiers).</li>
        <li>Profile and career information you provide.</li>
        <li>Documents you upload where the product allows it.</li>
        <li>Usage data, device/browser type, and approximate logs (e.g. IP, timestamps) for security and operations.</li>
        <li>Communications you send us (e.g. support requests).</li>
      </ul>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">3. How we use information</h2>
      <p>We use data to provide and improve the service, authenticate users, process applications, communicate with you, comply with law, and protect against abuse.</p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">4. Sharing</h2>
      <p>
        We may share data with service providers who assist us (e.g. hosting, email, analytics), when required by law, or to protect rights and safety.
        We do not sell your personal information as a commodity; if we use ad or analytics partners, their processing is governed by their policies and your settings where applicable.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">5. Retention</h2>
      <p>We keep information as long as needed for the purposes above and as required by law. You may request deletion as described on our data deletion page.</p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">6. Security</h2>
      <p>We use reasonable technical and organizational measures. No method of transmission or storage is 100% secure.</p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">7. Your rights</h2>
      <p>
        Depending on where you live, you may have rights to access, correct, delete, or restrict processing of your personal data, or to object or port data.
        Contact us at the email above. You may also have the right to complain to a supervisory authority.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">8. International transfers</h2>
      <p>If we process data across borders, we use appropriate safeguards where required by law.</p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">9. Children</h2>
      <p>The service is not directed at children under the age required in your jurisdiction. We do not knowingly collect their personal information.</p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">10. Changes</h2>
      <p>We may update this policy. We will post the revised version here and adjust the “Last updated” date.</p>
    </section>
  {/snippet}
</LegalDocPage>
