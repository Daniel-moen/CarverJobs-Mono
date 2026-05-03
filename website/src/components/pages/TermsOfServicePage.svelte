<script>
  import LegalDocPage from '../layout/LegalDocPage.svelte'
  import { supportEmail } from '../../config/site.js'
</script>

<LegalDocPage title="Terms of Service">
  {#snippet children()}
    <p class="text-xs text-slate-500">Last updated: 3 May 2026. Questions: <a class="text-cyan-500/90 underline hover:text-cyan-400" href="mailto:{supportEmail}">{supportEmail}</a>.</p>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">1. Agreement</h2>
      <p>
        By accessing or using CARVER, you agree to these Terms. If you disagree, do not use the service.
        We may change these Terms; continued use after changes means you accept the updated Terms.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">2. The service</h2>
      <p>
        CARVER provides tools to help crew discover opportunities and manage applications. Features may change, be suspended, or discontinued.
        We do not guarantee employment, interview outcomes, or third-party employer behaviour.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">3. Accounts</h2>
      <p>You are responsible for account security and for information you submit. You must provide accurate information and comply with applicable laws.</p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">4. Acceptable use</h2>
      <p>You will not misuse the service, attempt unauthorized access, scrape in violation of our rules, upload malware, harass others, or break the law.</p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">5. Content and intellectual property</h2>
      <p>
        We retain rights in the service and branding. You retain rights in content you provide; you grant us a licence to host, process, and display it as needed to run the service.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">6. Third parties</h2>
      <p>The service may link to or integrate third parties. Their terms and privacy practices apply to your use of their services.</p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">7. Fees</h2>
      <p>If paid features exist, pricing and billing terms are presented at purchase. Taxes may apply. Unless stated otherwise, fees are non-refundable to the extent permitted by law.</p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">8. Disclaimers</h2>
      <p>
        The service is provided “as is” and “as available” without warranties of any kind, to the fullest extent permitted by law.
        We disclaim implied warranties where allowable.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">9. Limitation of liability</h2>
      <p>
        To the maximum extent permitted by law, we are not liable for indirect, incidental, special, consequential, or punitive damages, or loss of profits, data, or goodwill.
        Our aggregate liability arising from these Terms or the service is limited to the greater of amounts you paid us in the twelve months before the claim or fifty (50) units of your local currency.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">10. Indemnity</h2>
      <p>You will defend and indemnify us against claims arising from your use of the service or violation of these Terms, to the extent permitted by law.</p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">11. Termination</h2>
      <p>We may suspend or terminate access for breach or risk. You may stop using the service at any time. Provisions that should survive will survive.</p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">12. Governing law</h2>
      <p>
        These Terms are governed by the laws of the jurisdiction you designate in your commercial agreements, or otherwise the laws applicable to the operator of the service,
        excluding conflict-of-law rules. Courts in that jurisdiction have exclusive venue, unless mandatory consumer law requires otherwise.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">13. Contact</h2>
      <p>
        Questions: <a class="text-cyan-400 underline hover:text-cyan-300" href="mailto:{supportEmail}">{supportEmail}</a>
      </p>
    </section>
  {/snippet}
</LegalDocPage>
