<script>
  import LegalDocPage from '../layout/LegalDocPage.svelte'
  import { supportEmail } from '../../config/site.js'
</script>

<LegalDocPage title="Refund Policy">
  {#snippet children()}
    <p class="text-xs text-slate-500">Last updated: 11 June 2026. Billing questions and refund requests: <a class="text-cyan-500/90 underline hover:text-cyan-400" href="mailto:{supportEmail}">{supportEmail}</a>.</p>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">1. What you are buying</h2>
      <p>
        CARVER sells <strong>tokens</strong> — prepaid digital credits used inside the service (for example,
        one token runs one job-matching session, and recruiter accounts spend tokens to unlock a candidate's
        contact details). Tokens are a digital good, delivered and credited to your balance immediately after
        a successful payment. All prices are shown and charged in South African Rand (ZAR) and processed by
        our payment provider, Yoco.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">2. Unused tokens — 14-day refund</h2>
      <p>
        If you change your mind, you may request a refund of tokens from a purchase within <strong>14 days</strong>
        of that purchase, <strong>provided none of the tokens from that purchase have been spent</strong>. We refund
        the amount paid for the unused tokens to your original payment method and remove those tokens from your
        balance. Once any token from a purchase has been used, that purchase is considered consumed and is no
        longer eligible for a change-of-mind refund.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">3. Consumed tokens are non-refundable</h2>
      <p>
        Because tokens unlock digital results immediately, tokens that have already been spent — including
        completed matching runs and recruiter contact unlocks — are non-refundable. A contact unlock is treated
        as consumed the moment the details are revealed to you.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">4. Billing errors and failed delivery</h2>
      <p>We will always make this right, regardless of the time limits above:</p>
      <ul class="list-inside list-disc space-y-1 text-slate-400">
        <li><strong>Duplicate or accidental charge:</strong> fully refunded.</li>
        <li><strong>Charged but tokens not delivered:</strong> we credit the tokens or refund the payment in full.</li>
        <li><strong>Incorrect amount charged:</strong> we refund the difference.</li>
        <li><strong>Unauthorised payment:</strong> contact us immediately so we can investigate and, where appropriate, refund.</li>
      </ul>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">5. Free and promotional tokens</h2>
      <p>
        Tokens granted free of charge — for example sign-up bonuses, job-posting rewards, or refunds of failed
        matching runs — have no cash value and are not redeemable for money. Only tokens you have paid for are
        eligible for a monetary refund.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">6. How to request a refund</h2>
      <p>
        Email <a class="text-cyan-400 underline hover:text-cyan-300" href="mailto:{supportEmail}">{supportEmail}</a>
        from the address on your account with your order reference and the reason for the request. We aim to
        respond within 2 business days. Approved refunds are returned to your original payment method via Yoco
        and typically appear within 5–10 business days, depending on your bank or card issuer.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">7. Your statutory rights</h2>
      <p>
        Nothing in this policy limits any rights you have under applicable consumer-protection law, including
        the South African Consumer Protection Act and the Electronic Communications and Transactions Act. Where
        the law gives you stronger rights than this policy, those rights apply.
      </p>
    </section>

    <section class="space-y-3">
      <h2 class="text-base font-semibold text-white">8. Changes</h2>
      <p>We may update this policy. We will post the revised version here and adjust the “Last updated” date. The policy in effect at the time of your purchase applies to that purchase.</p>
    </section>
  {/snippet}
</LegalDocPage>
