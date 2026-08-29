"""
The workspace markup, taken verbatim from the design canvas.

Kept as authored rather than hand-ported: the page is rendered by the
small template runtime in ui.py, which resolves {{ }} bindings and the
sc-if / sc-for tags the design uses. Editing the design and re-exporting
it should be a copy, not a translation.

Source: SDK dataset research assistant/Epsilon Assistant.dc.html
"""

STYLE = r'''html, body { margin: 0; padding: 0; background: #f4f2ee; }
  * { box-sizing: border-box; }
  a { color: #0d6459; text-decoration: none; border-bottom: 1px solid rgba(13,100,89,0.3); }
  a:hover { color: #0a4d44; border-bottom-color: #0a4d44; }
  @keyframes fadeUp { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
  ::-webkit-scrollbar { width: 10px; height: 10px; }
  ::-webkit-scrollbar-thumb { background: #d9d5cc; border-radius: 6px; border: 3px solid #f4f2ee; }'''

MARKUP = r'''<div style="display: flex; height: 100vh; min-height: 640px; font-family: 'IBM Plex Sans', system-ui, sans-serif; color: #1c1b19; background: #f4f2ee; overflow: hidden;">

  <div style="width: 236px; flex: 0 0 236px; background: #14201e; color: #cddcd8; display: flex; flex-direction: column; padding: 22px 0 16px;">
    <div style="padding: 0 20px 22px; display: flex; flex-direction: column; gap: 4px;">
      <div style="display: flex; align-items: baseline; gap: 8px;">
        <span style="font-family: 'IBM Plex Mono', monospace; font-size: 19px; font-weight: 600; color: #6fd3bd;">&#949;</span>
        <span style="font-family: 'IBM Plex Mono', monospace; font-size: 15px; font-weight: 500; letter-spacing: -0.01em; color: #f2f7f5;">epsilon ui</span>
      </div>
      <div style="font-family: 'IBM Plex Mono', monospace; font-size: 10.5px; color: #6d8480; letter-spacing: 0.02em;">127.0.0.1:7878 &middot; loopback</div>
    </div>

    <div style="padding: 0 12px; display: flex; flex-direction: column; gap: 2px;">
      <div onClick="{{ goSetup }}" style="display: flex; align-items: center; gap: 10px; padding: 9px 10px; border-radius: 6px; cursor: pointer; font-size: 13.5px; background: {{ navSetupBg }}; color: {{ navSetupFg }};">
        <span style="font-family: 'IBM Plex Mono', monospace; font-size: 11px; opacity: 0.6; width: 16px;">01</span>
        <span style="flex: 1;">Set up project</span>
        <sc-if value="{{ allDone }}" hint-placeholder-val="{{ false }}"><span style="color: #6fd3bd; font-size: 12px;">&#10003;</span></sc-if>
      </div>
      <div onClick="{{ goDataset }}" style="display: flex; align-items: center; gap: 10px; padding: 9px 10px; border-radius: 6px; cursor: pointer; font-size: 13.5px; background: {{ navDataBg }}; color: {{ navDataFg }};">
        <span style="font-family: 'IBM Plex Mono', monospace; font-size: 11px; opacity: 0.6; width: 16px;">02</span>
        <span style="flex: 1;">Dataset &amp; archetype</span>
        <sc-if value="{{ dataLocked }}" hint-placeholder-val="{{ false }}"><span style="font-size: 11px; opacity: 0.55;">&#9679;</span></sc-if>
      </div>
      <div onClick="{{ goChat }}" style="display: flex; align-items: center; gap: 10px; padding: 9px 10px; border-radius: 6px; cursor: pointer; font-size: 13.5px; background: {{ navChatBg }}; color: {{ navChatFg }};">
        <span style="font-family: 'IBM Plex Mono', monospace; font-size: 11px; opacity: 0.6; width: 16px;">03</span>
        <span style="flex: 1;">Assistant</span>
        <sc-if value="{{ chatLocked }}" hint-placeholder-val="{{ false }}"><span style="font-size: 11px; opacity: 0.55;">&#9679;</span></sc-if>
      </div>
    </div>

    <div style="flex: 1;"></div>

    <div style="margin: 0 12px; padding: 12px; border-radius: 6px; background: rgba(255,255,255,0.05); display: flex; flex-direction: column; gap: 7px;">
      <div style="font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; color: #6d8480;">Model</div>
      <div style="font-family: 'IBM Plex Mono', monospace; font-size: 11.5px; color: #e6efec;">{{ modelLine }}</div>
      <div style="font-size: 11px; line-height: 1.45; color: #93a8a4;">Your key, your machine. Calls go straight to the endpoint &mdash; Epsilon never sees a prompt.</div>
    </div>
  </div>

  <div style="flex: 1; min-width: 0; display: flex; flex-direction: column;">

    <sc-if value="{{ isSetup }}" hint-placeholder-val="{{ true }}">
      <div style="flex: 1; overflow-y: auto;">
        <div style="max-width: 860px; margin: 0 auto; padding: 46px 40px 80px;">
          <div style="font-family: 'IBM Plex Mono', monospace; font-size: 10.5px; letter-spacing: 0.12em; text-transform: uppercase; color: #8d887e; margin-bottom: 10px;">Getting started</div>
          <h1 style="margin: 0 0 12px; font-size: 30px; font-weight: 600; letter-spacing: -0.02em; line-height: 1.15;">Five commands, then you can ask the dataset questions</h1>
          <p style="margin: 0 0 30px; font-size: 15px; line-height: 1.6; color: #5c5850; max-width: 62ch; text-wrap: pretty;">The assistant only answers about a dataset that is already initialized in this project. It reads the archetype card the SDK downloaded and measures the projection on disk &mdash; so run these first.</p>

          <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap; padding: 14px 16px; background: #ffffff; border: 1px solid #e3e0d9; border-radius: 8px; margin-bottom: 28px;">
            <sc-for list="{{ flow }}" as="f" hint-placeholder-count="5">
              <div style="display: flex; align-items: center; gap: 6px;">
                <div style="font-family: 'IBM Plex Mono', monospace; font-size: 11.5px; padding: 5px 9px; border-radius: 5px; background: {{ f.bg }}; color: {{ f.fg }};">{{ f.label }}</div>
                <sc-if value="{{ f.arrow }}" hint-placeholder-val="{{ true }}"><span style="color: #b8b3a8; font-size: 12px;">&rarr;</span></sc-if>
              </div>
            </sc-for>
          </div>

          <div style="display: flex; flex-direction: column; gap: 14px;">
            <sc-for list="{{ steps }}" as="s" hint-placeholder-count="5">
              <div style="background: #ffffff; border: 1px solid {{ s.border }}; border-radius: 10px; overflow: hidden;">
                <div style="display: flex; gap: 16px; padding: 18px 20px;">
                  <div style="flex: 0 0 26px; height: 26px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-family: 'IBM Plex Mono', monospace; font-size: 11px; font-weight: 600; background: {{ s.badgeBg }}; color: {{ s.badgeFg }};">{{ s.badge }}</div>
                  <div style="flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 6px;">
                    <div style="display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap;">
                      <span style="font-size: 15.5px; font-weight: 600; letter-spacing: -0.01em;">{{ s.title }}</span>
                      <sc-if value="{{ s.optional }}" hint-placeholder-val="{{ false }}"><span style="font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase; color: #8a6212; background: #fbf3e0; padding: 2px 6px; border-radius: 4px;">needed for chat</span></sc-if>
                    </div>
                    <div style="font-size: 13.5px; line-height: 1.55; color: #5c5850; max-width: 60ch; text-wrap: pretty;">{{ s.desc }}</div>
                    <div style="display: flex; align-items: center; gap: 10px; margin-top: 6px; flex-wrap: wrap;">
                      <div style="font-family: 'IBM Plex Mono', monospace; font-size: 12.5px; padding: 8px 12px; border-radius: 6px; background: #14201e; color: #b9e5da; white-space: nowrap; overflow-x: auto;"><span style="color: #4f6a65;">$ </span>{{ s.cmd }}</div>
                      <sc-if value="{{ s.canRun }}" hint-placeholder-val="{{ true }}">
                        <div onClick="{{ s.run }}" style="font-size: 12.5px; font-weight: 500; padding: 8px 14px; border-radius: 6px; background: #0d6459; color: #ffffff; cursor: pointer;" style-hover="background: #0a4d44;">Run</div>
                      </sc-if>
                      <sc-if value="{{ s.isDone }}" hint-placeholder-val="{{ false }}">
                        <span style="font-family: 'IBM Plex Mono', monospace; font-size: 12px; color: #0d6459;">&#10003; done</span>
                      </sc-if>
                    </div>
                  </div>
                </div>

                <sc-if value="{{ s.showOutput }}" hint-placeholder-val="{{ false }}">
                  <div style="border-top: 1px solid #eceae4; background: #fbfaf8; padding: 14px 20px 16px 62px;">
                    <pre style="margin: 0; font-family: 'IBM Plex Mono', monospace; font-size: 12px; line-height: 1.65; color: #3f4b48; white-space: pre-wrap;">{{ s.output }}</pre>
                  </div>
                </sc-if>

                <sc-if value="{{ s.showPicker }}" hint-placeholder-val="{{ false }}">
                  <div style="border-top: 1px solid #eceae4; background: #fbfaf8; padding: 14px 20px 18px 62px;">
                    <div style="font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: #8d887e; margin-bottom: 10px;">3 datasets your access grants &mdash; select one to initialize</div>
                    <div style="display: flex; flex-direction: column; gap: 8px;">
                      <sc-for list="{{ datasets }}" as="d" hint-placeholder-count="3">
                        <div onClick="{{ d.pick }}" style="display: flex; align-items: center; gap: 14px; padding: 11px 14px; border: 1px solid {{ d.border }}; border-radius: 7px; background: {{ d.bg }}; cursor: pointer;">
                          <div style="flex: 1; min-width: 0;">
                            <div style="font-family: 'IBM Plex Mono', monospace; font-size: 12.5px; font-weight: 500;">{{ d.id }}</div>
                            <div style="font-size: 12px; color: #5c5850; margin-top: 3px;">{{ d.name }}</div>
                          </div>
                          <div style="font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: #8d887e; text-align: right;">
                            <div>{{ d.archetype }}</div>
                            <div style="margin-top: 3px;">{{ d.rows }}</div>
                          </div>
                          <div style="font-family: 'IBM Plex Mono', monospace; font-size: 11px; width: 58px; text-align: right; color: {{ d.markFg }};">{{ d.mark }}</div>
                        </div>
                      </sc-for>
                    </div>
                  </div>
                </sc-if>
              </div>
            </sc-for>
          </div>

          <sc-if value="{{ allDone }}" hint-placeholder-val="{{ false }}">
            <div style="margin-top: 26px; padding: 22px 24px; border-radius: 10px; background: #14201e; color: #dceae6; display: flex; align-items: center; gap: 24px; flex-wrap: wrap; animation: fadeUp .3s ease both;">
              <div style="flex: 1; min-width: 260px;">
                <div style="font-size: 17px; font-weight: 600; color: #ffffff; margin-bottom: 6px; letter-spacing: -0.01em;">Project is initialized. Now ask it what it can answer.</div>
                <div style="font-size: 13px; line-height: 1.55; color: #9db3ae; max-width: 56ch; text-wrap: pretty;">The assistant reads the card, checks feasibility against the same predicates <span style="font-family: 'IBM Plex Mono', monospace;">epsilon explain</span> uses, writes code and runs it against the synthetic data.</div>
              </div>
              <div onClick="{{ goChat }}" style="font-size: 14px; font-weight: 500; padding: 12px 20px; border-radius: 7px; background: #6fd3bd; color: #0c2a25; cursor: pointer; white-space: nowrap;" style-hover="background: #8ae0cd;">Open the assistant &rarr;</div>
            </div>
          </sc-if>
        </div>
      </div>
    </sc-if>

    <sc-if value="{{ isDataset }}" hint-placeholder-val="{{ false }}">
      <div style="flex: 1; overflow-y: auto;">
        <div style="max-width: 900px; margin: 0 auto; padding: 40px 40px 90px;">
          <div style="display: flex; align-items: flex-start; gap: 18px; flex-wrap: wrap; margin-bottom: 8px;">
            <div style="flex: 1; min-width: 280px;">
              <div style="font-family: 'IBM Plex Mono', monospace; font-size: 10.5px; letter-spacing: 0.12em; text-transform: uppercase; color: #8d887e; margin-bottom: 8px;">Dataset card</div>
              <h1 style="margin: 0 0 6px; font-size: 27px; font-weight: 600; letter-spacing: -0.02em;">{{ ds.name }}</h1>
              <div style="font-family: 'IBM Plex Mono', monospace; font-size: 12.5px; color: #5c5850;">{{ ds.id }}</div>
            </div>
            <div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 26px; padding: 14px 18px; background: #ffffff; border: 1px solid #e3e0d9; border-radius: 8px;">
              <sc-for list="{{ ds.facts }}" as="f" hint-placeholder-count="4">
                <div>
                  <div style="font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; letter-spacing: 0.08em; text-transform: uppercase; color: #8d887e;">{{ f.k }}</div>
                  <div style="font-family: 'IBM Plex Mono', monospace; font-size: 12.5px; margin-top: 3px;">{{ f.v }}</div>
                </div>
              </sc-for>
            </div>
          </div>

          <div style="margin: 30px 0 0; padding: 24px; background: #ffffff; border: 1px solid #e3e0d9; border-radius: 10px;">
            <h2 style="margin: 0 0 10px; font-size: 16px; font-weight: 600; letter-spacing: -0.01em;">What you actually have</h2>
            <p style="margin: 0 0 20px; font-size: 14px; line-height: 1.65; color: #4a463f; max-width: 68ch; text-wrap: pretty;">Not the source records. An <em style="font-style: normal; font-weight: 600;">archetype</em> is a fixed set of columns a data owner grants; the platform projects each record down to those columns and drops everything else, including every identifier. One consequence decides most of what you can and cannot compute: nothing in the projection groups two rows back to the same patient.</p>

            <div style="display: grid; grid-template-columns: 1fr 34px 1fr; gap: 0; align-items: stretch;">
              <div style="border: 1px solid #e8e5de; border-radius: 8px; padding: 16px; background: #fbfaf8;">
                <div style="font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; color: #8d887e; margin-bottom: 12px;">Source record (never leaves the enclave)</div>
                <div style="display: flex; flex-wrap: wrap; gap: 6px;">
                  <sc-for list="{{ sourceFields }}" as="f" hint-placeholder-count="8">
                    <div style="font-family: 'IBM Plex Mono', monospace; font-size: 11.5px; padding: 4px 8px; border-radius: 4px; background: {{ f.bg }}; color: {{ f.fg }}; text-decoration: {{ f.deco }};">{{ f.label }}</div>
                  </sc-for>
                </div>
              </div>
              <div style="display: flex; align-items: center; justify-content: center; color: #b8b3a8; font-size: 15px;">&rarr;</div>
              <div style="border: 1px solid #cfe3dd; border-radius: 8px; padding: 16px; background: #f4faf8;">
                <div style="font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; color: #0d6459; margin-bottom: 12px;">Projection you received &mdash; 10 columns</div>
                <div style="display: flex; flex-wrap: wrap; gap: 6px;">
                  <sc-for list="{{ grantedChips }}" as="f" hint-placeholder-count="10">
                    <div style="font-family: 'IBM Plex Mono', monospace; font-size: 11.5px; padding: 4px 8px; border-radius: 4px; background: #ffffff; border: 1px solid #cfe3dd; color: #0c4f46;">{{ f }}</div>
                  </sc-for>
                </div>
              </div>
            </div>
          </div>

          <div style="margin: 18px 0 0; background: #ffffff; border: 1px solid #e3e0d9; border-radius: 10px; overflow: hidden;">
            <div style="padding: 20px 24px 14px;">
              <h2 style="margin: 0 0 6px; font-size: 16px; font-weight: 600; letter-spacing: -0.01em;">Granted columns, as measured</h2>
              <p style="margin: 0; font-size: 13.5px; line-height: 1.6; color: #5c5850; max-width: 66ch;">Counted from the projection on disk by <span style="font-family: 'IBM Plex Mono', monospace;">epsilon init</span>. Nothing here was authored by hand, so nothing here can drift out of sync with the data.</p>
            </div>
            <div style="display: grid; grid-template-columns: 1.5fr 0.8fr 1.4fr 1.6fr; gap: 0; font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 0.07em; text-transform: uppercase; color: #8d887e; padding: 10px 24px; border-top: 1px solid #eceae4; border-bottom: 1px solid #eceae4; background: #fbfaf8;">
              <div>Column</div><div>Type</div><div>Measured</div><div>Note</div>
            </div>
            <sc-for list="{{ columns }}" as="c" hint-placeholder-count="10">
              <div style="display: grid; grid-template-columns: 1.5fr 0.8fr 1.4fr 1.6fr; gap: 0; padding: 11px 24px; border-bottom: 1px solid #f2f0eb; align-items: baseline;">
                <div style="font-family: 'IBM Plex Mono', monospace; font-size: 12.5px;">{{ c.name }}</div>
                <div style="font-family: 'IBM Plex Mono', monospace; font-size: 11.5px; color: #5c5850;">{{ c.type }}</div>
                <div style="font-family: 'IBM Plex Mono', monospace; font-size: 11.5px; color: #5c5850;">{{ c.measured }}</div>
                <div style="font-size: 12px; line-height: 1.45; color: {{ c.noteFg }};">{{ c.note }}</div>
              </div>
            </sc-for>
          </div>

          <div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; margin-top: 18px;">
            <div style="padding: 22px 24px; background: #ffffff; border: 1px solid #e3e0d9; border-radius: 10px;">
              <h2 style="margin: 0 0 12px; font-size: 15px; font-weight: 600;">Two traps, inferred from the data</h2>
              <div style="display: flex; flex-direction: column; gap: 14px;">
                <sc-for list="{{ traps }}" as="t" hint-placeholder-count="2">
                  <div style="display: flex; gap: 11px;">
                    <div style="flex: 0 0 3px; border-radius: 2px; background: #d9a53f;"></div>
                    <div>
                      <div style="font-family: 'IBM Plex Mono', monospace; font-size: 12px; margin-bottom: 4px;">{{ t.title }}</div>
                      <div style="font-size: 12.5px; line-height: 1.55; color: #5c5850; text-wrap: pretty;">{{ t.body }}</div>
                    </div>
                  </div>
                </sc-for>
              </div>
            </div>
            <div style="padding: 22px 24px; background: #ffffff; border: 1px solid #e3e0d9; border-radius: 10px;">
              <h2 style="margin: 0 0 12px; font-size: 15px; font-weight: 600;">What measurement cannot see</h2>
              <div style="display: flex; flex-direction: column; gap: 14px;">
                <sc-for list="{{ blind }}" as="t" hint-placeholder-count="2">
                  <div style="display: flex; gap: 11px;">
                    <div style="flex: 0 0 3px; border-radius: 2px; background: #b8b3a8;"></div>
                    <div>
                      <div style="font-family: 'IBM Plex Mono', monospace; font-size: 12px; margin-bottom: 4px;">{{ t.title }}</div>
                      <div style="font-size: 12.5px; line-height: 1.55; color: #5c5850; text-wrap: pretty;">{{ t.body }}</div>
                    </div>
                  </div>
                </sc-for>
              </div>
            </div>
          </div>

          <div onClick="{{ goChat }}" style="margin-top: 22px; padding: 18px 22px; border-radius: 10px; border: 1px dashed #c3bdb1; display: flex; align-items: center; gap: 16px; cursor: pointer; background: #ffffff;" style-hover="border-color: #0d6459;">
            <div style="flex: 1; font-size: 14px; line-height: 1.55; color: #4a463f;">Not sure which of these you can use? Ask the assistant &mdash; it reaches the same feasibility predicates through a tool.</div>
            <div style="font-family: 'IBM Plex Mono', monospace; font-size: 12.5px; color: #0d6459; white-space: nowrap;">open assistant &rarr;</div>
          </div>
        </div>
      </div>
    </sc-if>

    <sc-if value="{{ isChatLocked }}" hint-placeholder-val="{{ false }}">
      <div style="flex: 1; display: flex; align-items: center; justify-content: center; padding: 40px;">
        <div style="max-width: 460px; text-align: center;">
          <div style="font-family: 'IBM Plex Mono', monospace; font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: #8d887e; margin-bottom: 12px;">Assistant unavailable</div>
          <h2 style="margin: 0 0 12px; font-size: 21px; font-weight: 600; letter-spacing: -0.01em;">{{ lockTitle }}</h2>
          <p style="margin: 0 0 22px; font-size: 14px; line-height: 1.6; color: #5c5850; text-wrap: pretty;">{{ lockBody }}</p>
          <div onClick="{{ goSetup }}" style="display: inline-block; font-size: 13.5px; font-weight: 500; padding: 10px 18px; border-radius: 7px; background: #0d6459; color: #ffffff; cursor: pointer;">Back to setup</div>
        </div>
      </div>
    </sc-if>

    <sc-if value="{{ isChat }}" hint-placeholder-val="{{ false }}">
      <div style="flex: 1; display: flex; min-height: 0;">

        <div style="flex: 1; min-width: 0; display: flex; flex-direction: column;">
          <div style="padding: 14px 28px; border-bottom: 1px solid #e3e0d9; background: #f9f8f5; display: flex; align-items: center; gap: 14px;">
            <div style="flex: 1;">
              <div style="font-size: 14px; font-weight: 600; letter-spacing: -0.01em;">Assistant &middot; <span style="font-family: 'IBM Plex Mono', monospace; font-weight: 400; font-size: 13px; color: #5c5850;">{{ ds.id }}</span></div>
              <div style="font-size: 11.5px; color: #8d887e; margin-top: 2px;">Transcript saved to .epsilon/chat/, pinned to schema hash {{ ds.hashShort }}</div>
            </div>
            <div onClick="{{ reset }}" style="font-family: 'IBM Plex Mono', monospace; font-size: 11.5px; padding: 6px 11px; border-radius: 5px; border: 1px solid #ddd9d1; color: #5c5850; cursor: pointer; background: #ffffff;" style-hover="border-color: #b8b3a8;">clear</div>
          </div>

          <div style="flex: 1; overflow-y: auto; padding: 26px 28px 10px;">
            <div style="max-width: 720px; margin: 0 auto; display: flex; flex-direction: column; gap: 22px;">

              <sc-for list="{{ messages }}" as="m" hint-placeholder-count="2">
                <div style="animation: fadeUp .26s ease both;">
                  <sc-if value="{{ m.isUser }}" hint-placeholder-val="{{ false }}">
                    <div style="display: flex; justify-content: flex-end;">
                      <div style="max-width: 78%; padding: 11px 15px; border-radius: 10px 10px 3px 10px; background: #14201e; color: #eef5f3; font-size: 14px; line-height: 1.55;">{{ m.text }}</div>
                    </div>
                  </sc-if>

                  <sc-if value="{{ m.isBot }}" hint-placeholder-val="{{ true }}">
                    <div style="display: flex; gap: 13px;">
                      <div style="flex: 0 0 24px; height: 24px; border-radius: 50%; background: #dff0eb; color: #0d6459; display: flex; align-items: center; justify-content: center; font-family: 'IBM Plex Mono', monospace; font-size: 12px; font-weight: 600; margin-top: 2px;">&#949;</div>
                      <div style="flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 12px;">

                        <sc-for list="{{ m.blocks }}" as="b" hint-placeholder-count="2">
                          <div>
                            <sc-if value="{{ b.isText }}" hint-placeholder-val="{{ true }}">
                              <div style="font-size: 14.5px; line-height: 1.68; color: #26241f; text-wrap: pretty;">{{ b.text }}</div>
                            </sc-if>

                            <sc-if value="{{ b.isTool }}" hint-placeholder-val="{{ false }}">
                              <div style="display: inline-flex; align-items: center; gap: 9px; padding: 6px 11px; border-radius: 6px; background: #f0efea; border: 1px solid #e3e0d9;">
                                <span style="color: #0d6459; font-size: 11px;">&#10003;</span>
                                <span style="font-family: 'IBM Plex Mono', monospace; font-size: 11.5px; font-weight: 500;">{{ b.name }}</span>
                                <span style="font-family: 'IBM Plex Mono', monospace; font-size: 11.5px; color: #8d887e; overflow: hidden; text-overflow: ellipsis;">{{ b.arg }}</span>
                              </div>
                            </sc-if>

                            <sc-if value="{{ b.isNote }}" hint-placeholder-val="{{ false }}">
                              <div style="display: flex; gap: 11px; padding: 13px 15px; border-radius: 8px; background: #f9f8f5; border: 1px solid #e8e5de;">
                                <div style="flex: 0 0 3px; border-radius: 2px; background: #b8b3a8;"></div>
                                <div style="font-size: 13px; line-height: 1.6; color: #4a463f; text-wrap: pretty;">{{ b.text }}</div>
                              </div>
                            </sc-if>

                            <sc-if value="{{ b.isVerdict }}" hint-placeholder-val="{{ false }}">
                              <div style="border: 1px solid {{ b.border }}; border-radius: 9px; background: {{ b.bg }}; overflow: hidden;">
                                <div style="display: flex; align-items: center; gap: 10px; padding: 12px 16px; border-bottom: 1px solid {{ b.border }};">
                                  <span style="font-family: 'IBM Plex Mono', monospace; font-size: 11px; font-weight: 600; letter-spacing: 0.04em; padding: 3px 7px; border-radius: 4px; background: {{ b.tagBg }}; color: #ffffff;">{{ b.tag }}</span>
                                  <span style="font-family: 'IBM Plex Mono', monospace; font-size: 13.5px; font-weight: 500; color: {{ b.titleFg }};">{{ b.title }}</span>
                                </div>
                                <div style="padding: 13px 16px; display: flex; flex-direction: column; gap: 11px;">
                                  <div style="display: flex; gap: 10px;">
                                    <span style="font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: {{ b.labelFg }}; flex: 0 0 62px; padding-top: 2px;">{{ b.whyLabel }}</span>
                                    <span style="flex: 1; font-size: 13px; line-height: 1.6; color: #33302b; text-wrap: pretty;">{{ b.why }}</span>
                                  </div>
                                  <sc-if value="{{ b.hasUnlock }}" hint-placeholder-val="{{ false }}">
                                    <div style="display: flex; gap: 10px; padding-top: 10px; border-top: 1px solid {{ b.border }};">
                                      <span style="font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: {{ b.labelFg }}; flex: 0 0 62px; padding-top: 2px;">unlock</span>
                                      <span style="flex: 1; font-size: 13px; line-height: 1.6; color: #33302b; text-wrap: pretty;">{{ b.unlock }}</span>
                                    </div>
                                  </sc-if>
                                </div>
                              </div>
                            </sc-if>

                            <sc-if value="{{ b.isCode }}" hint-placeholder-val="{{ false }}">
                              <div style="border-radius: 9px; overflow: hidden; background: #14201e;">
                                <div style="display: flex; align-items: center; gap: 10px; padding: 9px 14px; border-bottom: 1px solid rgba(255,255,255,0.08);">
                                  <span style="font-family: 'IBM Plex Mono', monospace; font-size: 11.5px; color: #7f9c96;">{{ b.file }}</span>
                                  <span style="flex: 1;"></span>
                                  <span style="font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase; color: #6fd3bd;">{{ b.badge }}</span>
                                </div>
                                <pre style="margin: 0; padding: 14px 16px; font-family: 'IBM Plex Mono', monospace; font-size: 12px; line-height: 1.68; color: #d5e6e1; overflow-x: auto; white-space: pre;">{{ b.code }}</pre>
                              </div>
                            </sc-if>

                            <sc-if value="{{ b.isTable }}" hint-placeholder-val="{{ false }}">
                              <div style="border: 1px solid #e3e0d9; border-radius: 9px; background: #ffffff; overflow: hidden;">
                                <div style="padding: 10px 16px; border-bottom: 1px solid #eceae4; background: #fbfaf8; font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: #5c5850;">{{ b.caption }}</div>
                                <div style="display: grid; grid-template-columns: 1.3fr repeat(4, minmax(0, 1fr)); gap: 0;">
                                  <sc-for list="{{ b.head }}" as="h" hint-placeholder-count="5">
                                    <div style="padding: 9px 14px; font-family: 'IBM Plex Mono', monospace; font-size: 10.5px; letter-spacing: 0.05em; text-transform: uppercase; color: #8d887e; border-bottom: 1px solid #eceae4; text-align: {{ h.align }};">{{ h.t }}</div>
                                  </sc-for>
                                  <sc-for list="{{ b.cells }}" as="c" hint-placeholder-count="15">
                                    <div style="padding: 10px 14px; font-family: 'IBM Plex Mono', monospace; font-size: 12.5px; border-bottom: 1px solid #f4f2ed; text-align: {{ c.align }}; color: {{ c.fg }}; background: {{ c.bg }};">{{ c.t }}</div>
                                  </sc-for>
                                </div>
                                <div style="padding: 9px 16px; font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: #a33a2b; background: #fdf6f4;">{{ b.footer }}</div>
                              </div>
                            </sc-if>

                            <sc-if value="{{ b.isChart }}" hint-placeholder-val="{{ false }}">
                              <div style="border: 1px solid #e3e0d9; border-radius: 9px; background: #ffffff; padding: 18px 20px;">
                                <div style="display: flex; align-items: baseline; gap: 10px; margin-bottom: 16px;">
                                  <span style="font-size: 13.5px; font-weight: 600;">Admissions by type and gender</span>
                                  <span style="font-family: 'IBM Plex Mono', monospace; font-size: 10.5px; color: #8d887e;">analyses/_charts.py &rarr; SVG</span>
                                </div>
                                <div style="display: flex; flex-direction: column; gap: 14px;">
                                  <sc-for list="{{ chartGroups }}" as="g" hint-placeholder-count="4">
                                    <div>
                                      <div style="font-family: 'IBM Plex Mono', monospace; font-size: 11.5px; color: #4a463f; margin-bottom: 6px;">{{ g.label }}</div>
                                      <div style="display: flex; flex-direction: column; gap: 4px;">
                                        <sc-for list="{{ g.bars }}" as="bar" hint-placeholder-count="3">
                                          <div style="display: flex; align-items: center; gap: 9px;">
                                            <span style="font-family: 'IBM Plex Mono', monospace; font-size: 10.5px; color: #8d887e; flex: 0 0 74px;">{{ bar.who }}</span>
                                            <div style="flex: 1; height: 15px; position: relative; background: #f4f2ed; border-radius: 3px;">
                                              <div style="position: absolute; left: 0; top: 0; bottom: 0; width: {{ bar.w }}; border-radius: 3px; background: {{ bar.fill }}; border: {{ bar.border }};"></div>
                                            </div>
                                            <span style="font-family: 'IBM Plex Mono', monospace; font-size: 11.5px; flex: 0 0 68px; text-align: right; color: {{ bar.fg }};">{{ bar.v }}</span>
                                          </div>
                                        </sc-for>
                                      </div>
                                    </div>
                                  </sc-for>
                                </div>
                                <div style="margin-top: 16px; padding-top: 12px; border-top: 1px solid #eceae4; display: flex; align-items: center; gap: 16px; flex-wrap: wrap;">
                                  <div style="display: flex; align-items: center; gap: 7px;">
                                    <div style="width: 22px; height: 10px; border-radius: 2px; background: repeating-linear-gradient(45deg, #e6cfc9 0 3px, #fdf6f4 3px 6px); border: 1px dashed #c98d80;"></div>
                                    <span style="font-size: 11.5px; color: #5c5850;">suppressed, n &lt; 11 &mdash; drawn with no length</span>
                                  </div>
                                  <span style="font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: #8d887e;">3 levels held back</span>
                                </div>
                              </div>
                            </sc-if>

                            <sc-if value="{{ b.isStats }}" hint-placeholder-val="{{ false }}">
                              <div style="border: 1px solid #e3e0d9; border-radius: 9px; background: #ffffff; overflow: hidden;">
                                <div style="padding: 10px 16px; border-bottom: 1px solid #eceae4; background: #fbfaf8; font-family: 'IBM Plex Mono', monospace; font-size: 11.5px; color: #33302b;">{{ b.caption }}</div>
                                <div style="display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0;">
                                  <sc-for list="{{ b.stats }}" as="s" hint-placeholder-count="8">
                                    <div style="padding: 12px 16px; border-bottom: 1px solid #f4f2ed; border-right: 1px solid #f4f2ed;">
                                      <div style="font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; letter-spacing: 0.07em; text-transform: uppercase; color: #8d887e;">{{ s.k }}</div>
                                      <div style="font-family: 'IBM Plex Mono', monospace; font-size: 15px; margin-top: 4px; color: {{ s.fg }};">{{ s.v }}</div>
                                    </div>
                                  </sc-for>
                                </div>
                              </div>
                            </sc-if>
                          </div>
                        </sc-for>
                      </div>
                    </div>
                  </sc-if>
                </div>
              </sc-for>

              <sc-if value="{{ thinking }}" hint-placeholder-val="{{ false }}">
                <div style="display: flex; gap: 13px; align-items: center;">
                  <div style="flex: 0 0 24px; height: 24px; border-radius: 50%; background: #dff0eb; color: #0d6459; display: flex; align-items: center; justify-content: center; font-family: 'IBM Plex Mono', monospace; font-size: 12px; font-weight: 600;">&#949;</div>
                  <div style="font-family: 'IBM Plex Mono', monospace; font-size: 12px; color: #8d887e;">{{ thinkingLabel }}</div>
                </div>
              </sc-if>
            </div>
          </div>

          <div style="border-top: 1px solid #e3e0d9; background: #f9f8f5; padding: 14px 28px 18px;">
            <div style="max-width: 720px; margin: 0 auto;">
              <sc-if value="{{ hasChips }}" hint-placeholder-val="{{ true }}">
                <div style="display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px;">
                  <span style="font-family: 'IBM Plex Mono', monospace; font-size: 10.5px; letter-spacing: 0.06em; text-transform: uppercase; color: #8d887e; align-self: center;">Try</span>
                  <sc-for list="{{ chips }}" as="c" hint-placeholder-count="3">
                    <div onClick="{{ c.send }}" style="font-size: 12.5px; padding: 7px 12px; border-radius: 16px; background: #ffffff; border: 1px solid #ddd9d1; color: #33302b; cursor: pointer;" style-hover="border-color: #0d6459; color: #0d6459;">{{ c.label }}</div>
                  </sc-for>
                </div>
              </sc-if>
              <div style="display: flex; align-items: center; gap: 10px; padding: 11px 14px; background: #ffffff; border: 1px solid #ddd9d1; border-radius: 8px;">
                <span style="font-family: 'IBM Plex Mono', monospace; font-size: 13px; color: #b8b3a8;">&gt;</span>
                <div style="flex: 1; font-size: 13.5px; color: #a8a39a;">{{ inputHint }}</div>
                <div style="font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: #b8b3a8;">&#8629;</div>
              </div>
            </div>
          </div>
        </div>

        <div style="width: 292px; flex: 0 0 292px; border-left: 1px solid #e3e0d9; background: #f9f8f5; overflow-y: auto; padding: 20px 20px 32px;">
          <div style="font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: #8d887e; margin-bottom: 12px;">Feasibility &mdash; decided in code</div>
          <div style="display: flex; flex-direction: column; gap: 5px;">
            <sc-for list="{{ capabilities }}" as="c" hint-placeholder-count="10">
              <div style="display: flex; align-items: center; gap: 9px; padding: 8px 10px; background: #ffffff; border: 1px solid #e8e5de; border-radius: 6px;">
                <span style="font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; font-weight: 600; padding: 2px 5px; border-radius: 3px; background: {{ c.bg }}; color: #ffffff; flex: 0 0 auto; min-width: 34px; text-align: center;">{{ c.tag }}</span>
                <span style="font-family: 'IBM Plex Mono', monospace; font-size: 11.5px; color: #33302b;">{{ c.name }}</span>
              </div>
            </sc-for>
          </div>
          <div style="margin-top: 16px; font-size: 11.5px; line-height: 1.6; color: #5c5850; text-wrap: pretty;">Answered by <span style="font-family: 'IBM Plex Mono', monospace;">epsilon explain</span> from ordinary Python predicates. The assistant reaches the same predicates through a tool &mdash; it can phrase a verdict, never change one.</div>

          <div style="margin-top: 22px; padding-top: 18px; border-top: 1px solid #e3e0d9;">
            <div style="font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: #8d887e; margin-bottom: 12px;">Hard limits</div>
            <div style="display: flex; flex-direction: column; gap: 11px;">
              <sc-for list="{{ limits }}" as="l" hint-placeholder-count="3">
                <div style="display: flex; gap: 9px;">
                  <span style="color: #a33a2b; font-size: 12px; line-height: 1.5;">&#10005;</span>
                  <span style="font-size: 12px; line-height: 1.55; color: #4a463f; text-wrap: pretty;">{{ l }}</span>
                </div>
              </sc-for>
            </div>
          </div>
        </div>
      </div>
    </sc-if>
  </div>
</div>'''


# The design's own value derivation, verbatim. It calls the data
# methods below, which the runtime supplies from the live project
# rather than from the mockup's fixtures.
RENDER_VALS = r'''renderVals() {
    const st = this.state;
    const showTools = this.props.showToolCalls !== false;
    const allDone = st.done.every(Boolean);
    const initDone = st.done[3];
    const chatReady = initDone && st.done[4];
    const ds = this.ds();

    const navStyle = (active, enabled) => ({
      bg: active ? 'rgba(111,211,189,0.16)' : 'transparent',
      fg: active ? '#f2f7f5' : (enabled ? '#a9bdb8' : '#5f7570')
    });
    const nSetup = navStyle(st.view === 'setup', true);
    const nData = navStyle(st.view === 'dataset', initDone);
    const nChat = navStyle(st.view === 'chat', chatReady);

    const flowLabels = ['install', 'login', 'datasets', 'init', 'ai login', 'chat'];
    const flow = flowLabels.map((label, i) => {
      const reached = i < 5 ? st.done[i] : chatReady;
      return {
        label: label,
        arrow: i < flowLabels.length - 1,
        bg: reached ? '#dff0eb' : '#f4f2ed',
        fg: reached ? '#0c4f46' : '#8d887e'
      };
    });

    const steps = this.stepDefs().map((s, i) => {
      const done = st.done[i];
      const isPicker = !!s.picker;
      return {
        badge: done ? '\u2713' : String(i + 1),
        badgeBg: done ? '#0d6459' : '#f0efea',
        badgeFg: done ? '#ffffff' : '#5c5850',
        border: done ? '#dbe8e4' : '#e3e0d9',
        title: s.title,
        desc: s.desc,
        cmd: isPicker && st.picked ? s.cmd : s.cmd,
        optional: !!s.optional,
        canRun: !done && !isPicker,
        isDone: done,
        showOutput: done && !isPicker,
        showPicker: isPicker && (done || st.done[1]),
        output: s.output,
        run: () => this.runStep(i)
      };
    });
    steps[3].cmd = st.picked ? 'epsilon init ' + st.picked : 'epsilon init <dataset_id>';
    steps[3].canRun = !st.done[3] && !!st.picked;

    const datasets = this.datasetList().map(d => {
      const sel = st.picked === d.id;
      return {
        id: d.id, name: d.name, archetype: d.archetype, rows: d.rows,
        bg: sel ? '#f4faf8' : '#ffffff',
        border: sel ? '#0d6459' : '#e8e5de',
        mark: sel ? 'selected' : 'select',
        markFg: sel ? '#0d6459' : '#b8b3a8',
        pick: () => this.pick(d.id)
      };
    });

    const columns = this.columnDefs().map(c => ({
      name: c.name, type: c.type, measured: c.measured,
      note: c.note || '\u2014',
      noteFg: c.warn ? '#8a6212' : '#8d887e'
    }));

    const stripped = ['patient_id', 'mrn', 'admission_id', 'site_id', 'notes.text', 'clinician_id'];
    const sourceFields = stripped.map(f => ({
      label: f, bg: '#f7edeb', fg: '#a33a2b', deco: 'line-through'
    })).concat(['patient.gender', 'admissions.type', '+ 8 more'].map(f => ({
      label: f, bg: '#ffffff', fg: '#5c5850', deco: 'none'
    })));

    const grantedChips = this.columnDefs().map(c => c.name);

    const verdictStyle = {
      yes: { tag: 'YES', tagBg: '#0d6459', bg: '#f4faf8', border: '#cfe3dd', titleFg: '#0c4f46', labelFg: '#5b8b82', whyLabel: 'why' },
      no: { tag: 'NO', tagBg: '#a33a2b', bg: '#fdf6f4', border: '#ecd7d1', titleFg: '#8c3123', labelFg: '#a8776c', whyLabel: 'why not' },
      warn: { tag: 'WARN', tagBg: '#8a6212', bg: '#fdf9f0', border: '#eadfc4', titleFg: '#7a5610', labelFg: '#a08a5c', whyLabel: 'caveat' }
    };

    const tableBlock = () => {
      const head = ['', 'Emergency', 'Elective', 'Transfer', 'Urgent'].map((t, i) => ({ t: t, align: i === 0 ? 'left' : 'right' }));
      const rows = [
        ['Female', '9,412', '3,180', '1,204', '2,377'],
        ['Male', '11,860', '3,742', '1,489', '2,905'],
        ['Other / n.r.', '\u2014 suppressed', '14', '\u2014 suppressed', '21']
      ];
      const cells = [];
      rows.forEach(r => {
        r.forEach((t, i) => {
          const sup = t.indexOf('suppressed') > -1;
          cells.push({
            t: t, align: i === 0 ? 'left' : 'right',
            fg: sup ? '#a33a2b' : (i === 0 ? '#33302b' : '#1c1b19'),
            bg: sup ? '#fdf6f4' : 'transparent'
          });
        });
      });
      return { isTable: true, head: head, cells: cells, caption: 'main() \u2192 36,204 of 41,208 rows \u00b7 gender null in 5,004', footer: '2 cells below n = 11 \u2014 withheld from the released result' };
    };

    const statsBlock = () => ({
      isStats: true,
      caption: 'profile_field(patient.age_years) \u00b7 aggregates only',
      stats: [
        { k: 'type', v: 'int', fg: '#1c1b19' }, { k: 'non-null', v: '41,208', fg: '#1c1b19' },
        { k: 'null rate', v: '0.0%', fg: '#1c1b19' }, { k: 'distinct', v: '73', fg: '#1c1b19' },
        { k: 'min', v: '18', fg: '#1c1b19' }, { k: 'median', v: '61', fg: '#1c1b19' },
        { k: 'p75', v: '76', fg: '#1c1b19' }, { k: 'max', v: '90 \u26a0', fg: '#8a6212' }
      ]
    });

    const script = this.script();
    const byId = {};
    script.forEach(s => { byId[s.id] = s; });

    const messages = [];
    st.shown.forEach(id => {
      const turn = byId[id];
      if (!turn) return;
      messages.push({ isUser: true, isBot: false, text: turn.prompt });
      if (st.thinking === id) return;
      const blocks = [];
      turn.blocks.forEach(b => {
        if (b.kind === 'tool') {
          if (showTools) blocks.push({ isTool: true, name: b.name, arg: b.arg });
        } else if (b.kind === 'text') {
          blocks.push({ isText: true, text: b.text });
        } else if (b.kind === 'note') {
          blocks.push({ isNote: true, text: b.text });
        } else if (b.kind === 'code') {
          blocks.push({ isCode: true, file: b.file, badge: b.badge, code: b.code });
        } else if (b.kind === 'table') {
          blocks.push(tableBlock());
        } else if (b.kind === 'stats') {
          blocks.push(statsBlock());
        } else if (b.kind === 'chart') {
          blocks.push({ isChart: true });
        } else if (b.kind === 'verdict') {
          const s = verdictStyle[b.level];
          blocks.push({
            isVerdict: true, tag: s.tag, tagBg: s.tagBg, bg: s.bg, border: s.border,
            titleFg: s.titleFg, labelFg: s.labelFg, whyLabel: s.whyLabel,
            title: b.title, why: b.why, unlock: b.unlock || '', hasUnlock: !!b.unlock
          });
        }
      });
      messages.push({ isUser: false, isBot: true, blocks: blocks });
    });

    if (messages.length === 0) {
      messages.push({
        isUser: false, isBot: true, blocks: [
          { isText: true, text: 'Project initialized against nordic-icu-2019. I have read the card for icu_encounter_v3 and measured the projection on disk \u2014 ten columns, 41,208 rows, suppression threshold 11.' },
          { isText: true, text: 'Describe what you want to find out and I will check whether this archetype can answer it, write the analysis and run it against the synthetic data. Where the answer is no, you get the reason and what would unlock it.' }
        ]
      });
    }

    const chips = script.filter(s => st.shown.indexOf(s.id) === -1).slice(0, 3)
      .map(s => ({ label: s.prompt, send: () => this.send(s.id) }));

    const g = (label, f, m, sup) => ({
      label: label,
      bars: [
        { who: 'Female', v: f.v, w: f.w, fill: '#0d6459', border: 'none', fg: '#1c1b19' },
        { who: 'Male', v: m.v, w: m.w, fill: '#6fb8a8', border: 'none', fg: '#1c1b19' },
        sup
          ? { who: 'Other / n.r.', v: 'n < 11', w: '26px', fill: 'repeating-linear-gradient(45deg, #e6cfc9 0 3px, #fdf6f4 3px 6px)', border: '1px dashed #c98d80', fg: '#a33a2b' }
          : { who: 'Other / n.r.', v: '14', w: '0.9%', fill: '#c9d9d5', border: 'none', fg: '#5c5850' }
      ]
    });

    const chartGroups = [
      g('Emergency', { v: '9,412', w: '78.4%' }, { v: '11,860', w: '98.8%' }, true),
      g('Elective', { v: '3,180', w: '26.5%' }, { v: '3,742', w: '31.2%' }, false),
      g('Transfer', { v: '1,204', w: '10.0%' }, { v: '1,489', w: '12.4%' }, true),
      g('Urgent', { v: '2,377', w: '19.8%' }, { v: '2,905', w: '24.2%' }, true)
    ];

    const capabilities = this.capabilityDefs().map(c => ({
      tag: c.tag, name: c.name,
      bg: c.tag === 'YES' ? '#0d6459' : (c.tag === 'NO' ? '#a33a2b' : '#8a6212')
    }));

    return {
      isSetup: st.view === 'setup',
      isDataset: st.view === 'dataset' && initDone,
      isChat: st.view === 'chat' && chatReady,
      isChatLocked: st.view === 'chat' && !chatReady,
      lockTitle: initDone ? 'No model is configured' : 'No dataset is initialized yet',
      lockBody: initDone
        ? 'epsilon chat needs a tier-A model, and the key stays on your machine. Run epsilon ai login \u2014 everything else in the SDK works without one.'
        : 'The assistant answers from a dataset card the SDK has downloaded. Run epsilon init with a dataset id first, then come back.',
      goSetup: () => this.go('setup'),
      goDataset: () => { if (initDone) this.go('dataset'); },
      goChat: () => this.go('chat'),
      reset: () => this.setState({ shown: [], thinking: null }),
      navSetupBg: nSetup.bg, navSetupFg: nSetup.fg,
      navDataBg: nData.bg, navDataFg: nData.fg,
      navChatBg: nChat.bg, navChatFg: nChat.fg,
      dataLocked: !initDone, chatLocked: !chatReady, allDone: allDone,
      modelLine: st.done[4] ? 'claude-sonnet-5 \u00b7 tier A' : 'not configured',
      flow: flow, steps: steps, datasets: datasets,
      ds: ds, columns: columns, sourceFields: sourceFields, grantedChips: grantedChips,
      traps: [
        { title: 'top-coded maximum', body: 'A pile-up at the largest value of patient.age_years. Ages above 90 are collapsed onto 90 for de-identification, so the column has a ceiling rather than a tail.' },
        { title: 'code beside a version', body: 'dx.code is paired with dx.code_version. One clinical concept can carry a different code per revision, so counting codes across revisions splits or merges concepts silently.' }
      ],
      blind: [
        { title: 'per-entity date shift', body: 'admissions.admit_ts is shifted per entity, and a shifted date is indistinguishable from a real one. Nothing can measure this, so trend analysis warns instead of blocking.' },
        { title: 'which date starts a clock', body: 'An archetype grants columns, not the semantics tying them together. Survival is blocked outright rather than guessed at.' },
        { title: 'no key back to an entity', body: 'Identifiers are stripped at projection, so no measurement will ever find one. Prevalence, regression and two-group comparison stay blocked until an owner grants a pseudonymised key.' }
      ],
      messages: messages, chips: chips, hasChips: chips.length > 0,
      thinking: !!st.thinking,
      thinkingLabel: 'reading the card, checking feasibility\u2026',
      inputHint: chips.length > 0 ? 'Ask about the dataset, or pick a suggestion above' : 'Ask anything about icu_encounter_v3',
      capabilities: capabilities,
      chartGroups: chartGroups,
      limits: [
        'Cannot overrule a feasibility verdict \u2014 a blocked analysis produces a refusal it has to relay.',
        'Cannot read a record. profile_field returns aggregates with rare levels suppressed, and only where the owner allowed profiling.',
        'Cannot leave the project directory, or write into generated/.'
      ]
    };
  }'''


# The runtime that renders MARKUP with live data.
RUNTIME = r'''
// ---------------------------------------------------------------------------
// A small renderer for the three constructs the design's markup uses:
// {{ bindings }}, <sc-if value="{{ x }}">, and <sc-for list="{{ xs }}" as="v">.
// The markup itself is kept verbatim, so re-exporting the design is a copy
// rather than a translation.
// ---------------------------------------------------------------------------

const HANDLERS = {};
let HID = 0;

function get(path, scope){
  if (path === "true") return true;
  if (path === "false") return false;
  let v = scope;
  for (const part of path.split(".")) {
    if (v == null) return undefined;
    v = v[part];
  }
  return v;
}

function esc(t){
  return String(t == null ? "" : t)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
    .replace(/"/g,"&quot;");
}

// A binding used as onClick becomes a real handler; everything else is text.
function subst(chunk, scope){
  chunk = chunk.replace(/onClick="\{\{\s*([\w.]+)\s*\}\}"/g, (_, path) => {
    const fn = get(path, scope);
    if (typeof fn !== "function") return "";
    const id = "h" + (++HID);
    HANDLERS[id] = fn;
    return 'data-h="' + id + '"';
  });
  return chunk.replace(/\{\{\s*([\w.]+)\s*\}\}/g, (_, path) => {
    const v = get(path, scope);
    return v == null ? "" : esc(v);
  });
}

function findClose(tpl, from, tag){
  const open = new RegExp("<" + tag + "\\b", "g");
  const close = new RegExp("</" + tag + ">", "g");
  let depth = 1, i = from;
  while (i < tpl.length) {
    open.lastIndex = close.lastIndex = i;
    const o = open.exec(tpl), c = close.exec(tpl);
    if (!c) return { start: tpl.length, end: tpl.length };
    if (o && o.index < c.index) { depth++; i = o.index + 1; continue; }
    depth--;
    if (depth === 0) return { start: c.index, end: c.index + c[0].length };
    i = c.index + 1;
  }
  return { start: tpl.length, end: tpl.length };
}

function expand(tpl, scope){
  let out = "", i = 0;
  for (;;) {
    const m = /<sc-(for|if)\b[^>]*>/.exec(tpl.slice(i));
    if (!m) { out += subst(tpl.slice(i), scope); break; }
    const start = i + m.index;
    out += subst(tpl.slice(i, start), scope);
    const tag = "sc-" + m[1];
    const openEnd = start + m[0].length;
    const close = findClose(tpl, openEnd, tag);
    const inner = tpl.slice(openEnd, close.start);
    if (m[1] === "if") {
      const cond = m[0].match(/value="\{\{\s*([\w.]+)\s*\}\}"/);
      if (cond && get(cond[1], scope)) out += expand(inner, scope);
    } else {
      const list = m[0].match(/list="\{\{\s*([\w.]+)\s*\}\}"/);
      const as = m[0].match(/as="(\w+)"/);
      const items = (list ? get(list[1], scope) : null) || [];
      for (const item of items) {
        const child = Object.create(scope);
        child[as ? as[1] : "it"] = item;
        out += expand(inner, child);
      }
    }
    i = close.end;
  }
  return out;
}

// ---------------------------------------------------------------------------
// A model answers in markdown; the design renders typed blocks. Without this,
// a generated script arrives as one unbroken paragraph with backticks in it.
// ---------------------------------------------------------------------------

const FENCE = /```([\w.+-]*)[ \t]*\r?\n([\s\S]*?)```/g;

// Markdown a plain-text block cannot show: the markers would render literally.
function tidy(md){
  return md
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/(^|\s)\*([^*\n]+)\*/g, "$1$2")
    .replace(/^#{1,6}[ \t]*/gm, "")
    .replace(/`([^`\n]+)`/g, "$1")
    .replace(/^[ \t]*[-*][ \t]+/gm, "• ")
    .replace(/[ \t]+$/gm, "")
    .trim();
}

// A markdown table: a header row, a |---| rule, then body rows.
function asTable(para){
  const lines = para.split("\n").map(l => l.trim()).filter(Boolean);
  if (lines.length < 3 || !lines[0].startsWith("|")) return null;
  if (!/^\|[\s:|-]+\|$/.test(lines[1])) return null;

  const split = row => row.replace(/^\||\|$/g, "").split("|").map(c => c.trim());
  const head = split(lines[0]);
  const rows = lines.slice(2).map(split).filter(r => r.length === head.length);
  if (!rows.length) return null;

  const cells = [];
  rows.forEach(r => r.forEach((t, i) => {
    // A withheld cell is the point of the suppression rule; show it as such.
    const withheld = /suppressed|^none$|^null$|^-+$/i.test(t) || t === "";
    cells.push({
      t: withheld ? "— suppressed" : t,
      align: i === 0 ? "left" : "right",
      fg: withheld ? "#a33a2b" : (i === 0 ? "#33302b" : "#1c1b19"),
      bg: withheld ? "#fdf6f4" : "transparent"
    });
  }));

  return {
    kind: "table",
    head: head.map((t, i) => ({ t: t, align: i === 0 ? "left" : "right" })),
    cells: cells,
    grid: "1.3fr repeat(" + (head.length - 1) + ", minmax(0, 1fr))",
    caption: rows.length + (rows.length === 1 ? " row" : " rows"),
    footer: ""
  };
}

function pushProse(blocks, raw){
  const text = tidy(raw || "");
  if (!text) return;
  // Blank lines are paragraph breaks; the design renders one block per idea.
  for (const para of text.split(/\n{2,}/)) {
    const t = para.trim();
    if (!t) continue;
    const table = asTable(t);
    if (table) blocks.push(table);
    else blocks.push({ kind: "text", text: t });
  }
}

function parseReply(reply){
  const blocks = [];
  let last = 0, m;
  FENCE.lastIndex = 0;
  while ((m = FENCE.exec(reply)) !== null) {
    const before = reply.slice(last, m.index);
    pushProse(blocks, before);
    // The last filename mentioned before the fence labels the panel.
    const named = before.match(/[\w./-]+\.(?:py|json|csv|md|svg)/g);
    blocks.push({
      kind: "code",
      code: m[2].replace(/\s+$/, ""),
      file: named ? named[named.length - 1] : "snippet",
      badge: m[1] || "python"
    });
    last = FENCE.lastIndex;
  }
  pushProse(blocks, reply.slice(last));
  return blocks;
}

// A chart drawn from the released result, never from anything the model wrote.
function chartBlock(c){
  let top = 0;
  for (const g of c.groups) for (const p of g.pairs) top = Math.max(top, p[1]);
  const palette = ["#0d6459", "#6fb8a8", "#a8cfc6", "#cfe3dd"];
  return {
    kind: "chart",
    title: c.title,
    caption: c.source + (c.held ? " · " + c.held + " below the threshold, withheld" : ""),
    groups: c.groups.map(g => ({
      label: g.label,
      bars: g.pairs.map((p, i) => ({
        who: String(p[0]).slice(0, 14),
        v: typeof p[1] === "number" ? p[1].toLocaleString() : String(p[1]),
        w: (top ? Math.max(2, Math.round(100 * p[1] / top)) : 0) + "%",
        fill: palette[i % palette.length],
        border: "none",
        fg: "#1c1b19"
      }))
    }))
  };
}

// ---------------------------------------------------------------------------
// The component. renderVals() below is the design's own, unmodified; it calls
// the data methods, which read the live project instead of the mockup's
// fixtures.
// ---------------------------------------------------------------------------

class App {
  constructor(){
    this.props = { showToolCalls: true };
    this.state = { view: "setup", done: [false,false,false,false,false],
                   picked: null, shown: [], thinking: null };
    this.api = { status: null, dataset: null, analyses: [], model: null };
    this.turns = [];
  }

  setState(patch){ Object.assign(this.state, patch); this.paint(); }

  async load(){
    const j = async p => (await fetch(p)).json();
    this.api.status = await j("/api/status");
    this.api.dataset = await j("/api/dataset");
    this.api.analyses = this.api.dataset.ready ? (await j("/api/analyses")).analyses : [];
    const s = this.api.status;
    this.state.done = s.steps.map(x => !!x.done);
    if (s.hasProject && this.state.view === "setup" && this.state.done.every(Boolean))
      this.state.view = this.state.view;
    this.paint();
  }

  // -- data the design asks for, from the live project --------------------

  ds(){
    const d = this.api.dataset || {};
    return {
      id: d.archetype || "—",
      name: d.title || "No project yet",
      hashShort: d.schemaHash || "not pinned",
      facts: [
        { k: "archetype", v: d.archetype || "—" },
        { k: "rows", v: d.rows != null ? d.rows.toLocaleString() : "—" },
        { k: "schema_hash", v: d.schemaHash ? d.schemaHash + " ✓" : "not pinned" },
        { k: "suppression", v: "n < " + (d.minCell != null ? d.minCell : 10) }
      ]
    };
  }

  stepDefs(){
    return (this.api.status ? this.api.status.steps : []).map(s => ({
      title: s.title, desc: s.desc, cmd: s.cmd, output: s.note,
      optional: !!s.optional, picker: s.key === "datasets"
    }));
  }

  datasetList(){ return []; }   // the picker needs an authenticated hub call

  columnDefs(){
    const d = this.api.dataset || { fields: [] };
    return (d.fields || []).map(f => {
      let measured = f.type;
      if (f.range) measured = f.range[0] + "–" + f.range[1];
      else if (f.categories && f.categories.length)
        measured = f.categories.slice(0, 3).join(", ") +
          (f.cardinality > 3 ? ", …" : "");
      else if (f.cardinality) measured = f.cardinality.toLocaleString() + " distinct";
      return {
        name: f.path, type: f.type, measured: measured,
        note: f.caveats && f.caveats.length ? f.caveats[0]
              : (f.access !== "DETAILED"
                 ? "released as " + (f.releasableAs || []).join(" · ") : ""),
        warn: !!(f.caveats && f.caveats.length) || f.access !== "DETAILED"
      };
    });
  }

  capabilityDefs(){
    return this.api.analyses.map(m => ({
      tag: m.status === "FEASIBLE" ? "YES" : "NO", name: m.key
    }));
  }

  script(){ return this.turns; }

  // -- handlers ------------------------------------------------------------

  go(view){ this.setState({ view: view }); }
  pick(id){ this.setState({ picked: id }); }
  runStep(){ /* set-up steps are run in a terminal; the card shows the command */ }

  async send(text){
    const q = (text || "").trim();
    if (!q) return;
    const id = "t" + this.turns.length;
    this.turns.push({ id: id, prompt: q, blocks: [] });
    this.setState({ shown: this.state.shown.concat([id]), thinking: id });
    const r = await (await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: q })
    })).json();
    const turn = this.turns[this.turns.length - 1];
    for (const s of (r.steps || [])) {
      const bits = String(s.label).match(/^(\w+)(?:\((.*)\))?$/);
      turn.blocks.push({ kind: "tool", name: bits ? bits[1] : s.label,
                         arg: bits && bits[2] ? bits[2] : "" });
    }
    for (const b of parseReply(r.reply || r.error || "")) turn.blocks.push(b);
    for (const c of (r.charts || [])) turn.blocks.push(chartBlock(c));
    this.setState({ thinking: null });
  }

  paint(){
    // The whole tree is re-rendered, so anything half-typed has to be carried
    // across or a reply would wipe the box mid-sentence.
    const prev = document.getElementById("ask");
    const carry = prev
      ? { value: prev.value, focused: document.activeElement === prev }
      : null;

    const vals = this.renderVals();
    const root = document.getElementById("root");
    for (const k of Object.keys(HANDLERS)) delete HANDLERS[k];
    root.innerHTML = expand(MARKUP, vals);
    root.querySelectorAll("[data-h]").forEach(el => {
      const fn = HANDLERS[el.getAttribute("data-h")];
      if (fn) el.addEventListener("click", ev => { ev.preventDefault(); fn(); });
    });

    const input = document.getElementById("ask");
    if (!input) return;
    if (carry) input.value = carry.value;
    input.addEventListener("keydown", ev => {
      if (ev.key !== "Enter" || ev.isComposing) return;
      ev.preventDefault();
      const text = input.value;
      input.value = "";
      this.send(text);
    });
    if (this.state.view === "chat" && (!carry || carry.focused)) {
      input.focus();
      const end = input.value.length;
      try { input.setSelectionRange(end, end); } catch (e) { /* not selectable */ }
    }
  }
}

App.prototype.renderVals = RENDER_VALS_FN;

// The design's renderVals carries the mockup's fixtures for the handful of
// values it could not know at design time. Everything structural and every
// colour stays exactly as authored; only the content is replaced with what
// was measured from this project.
App.prototype.localise = function(v){
  const d = this.api.dataset || {};
  const st = this.api.status || {};
  const cols = (d.fields || []).map(f => f.path);

  // The source record is not on this machine, so name what was removed in
  // kind rather than inventing column names we have never seen.
  v.sourceFields = (d.stripped || []).map(x => ({
    label: x, bg: "#f7edeb", fg: "#a33a2b", deco: "line-through"
  })).concat(cols.slice(0, 2).map(f => ({
    label: f, bg: "#ffffff", fg: "#5c5850", deco: "none"
  }))).concat(cols.length > 2 ? [{
    label: "+ " + (cols.length - 2) + " more", bg: "#ffffff",
    fg: "#5c5850", deco: "none"
  }] : []);
  v.grantedCount = d.granted != null ? d.granted : cols.length;

  const m = st.model;
  v.modelLine = m ? (m.model + " · tier " + m.tier) : "no model configured";
  v.inputHint = d.ready
    ? "Ask anything about " + (d.archetype || "this dataset")
    : "Initialise a project first";

  // Traps are whatever the measurement actually flagged, per column.
  const traps = [];
  (d.fields || []).forEach(f => (f.caveats || []).forEach(c =>
    traps.push({ title: f.path, body: c })));
  v.traps = traps;

  // What no measurement can see. These are properties of the platform, not
  // of any one dataset, so they are stated rather than inferred.
  v.blind = [
    { title: "per-entity date shift",
      body: "A date shifted by a per-entity offset is indistinguishable from a "
          + "real one. Nothing can measure this, so trend analysis warns "
          + "instead of blocking." },
    { title: "which date starts a clock",
      body: "An archetype grants columns, not the semantics tying them "
          + "together. Survival is blocked outright rather than guessed at." },
    { title: "no key back to an entity",
      body: "Identifiers are stripped at projection, so no measurement will "
          + "ever find one. Prevalence, regression and two-group comparison "
          + "stay blocked until an owner grants a pseudonymised key." }
  ];

  v.limits = [
    "Cannot overrule a feasibility verdict — a blocked analysis produces a "
      + "refusal it has to relay.",
    "Cannot read a record. profile_field returns aggregates over the local "
      + "synthetic projection, with rare levels withheld.",
    "Cannot leave the project directory, or write into generated/."
  ];

  if (!m) {
    v.lockTitle = "Assistant needs a model";
    v.lockBody = "Run epsilon ai login in a terminal and reload. Your key stays "
      + "in this machine's keyring and calls go straight to the endpoint — "
      + "Epsilon never sees a prompt. Every other panel works without one.";
  } else if (!d.ready) {
    v.lockTitle = "No project yet";
    v.lockBody = "The assistant only answers about a dataset already "
      + "initialised here. Finish set-up first.";
  }

  v.chips = (d.ready && !this.turns.length) ? [
    { label: "What can I compute with this dataset?",
      send: () => this.send("What can I compute with this dataset, and what can't I?") },
    { label: "Why is prevalence blocked?",
      send: () => this.send("Why is prevalence blocked here, and what would unlock it?") },
    { label: "Cross-tab two columns and run it",
      send: () => this.send("Cross-tab two categorical columns, generate the code and run it.") }
  ] : [];
  v.hasChips = v.chips.length > 0;

  if (!this.turns.length && d.ready) {
    v.messages = [{ isUser: false, isBot: true, blocks: [
      { isText: true, text:
        "Project initialised against " + (d.archetype || "this archetype") +
        ". I have measured the projection on disk — " + v.grantedCount +
        " columns, " + (d.rows != null ? d.rows.toLocaleString() : "?") +
        " rows, one row per " + (d.unit || "record") +
        ", suppression threshold " + (d.minCell != null ? d.minCell : 10) + "." },
      { isText: true, text:
        "Describe what you want to find out and I will check whether this "
        + "archetype can answer it, write the analysis and run it against the "
        + "synthetic data. Where the answer is no, you get the reason and what "
        + "would unlock it." }
    ]}];
  }
  return v;
};

const DESIGN_RENDER_VALS = App.prototype.renderVals;
App.prototype.renderVals = function(){
  return this.localise(DESIGN_RENDER_VALS.call(this));
};

const APP = new App();
APP.load();
'''
