# bot.py （日本語スラッシュコマンド + nuggets版）
import os
import discord
from discord.ext import commands
from discord import app_commands

import bank  # 同じフォルダの bank.py
import random

# 環境変数 DISCORD_TOKEN からトークン取得
TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("環境変数 DISCORD_TOKEN が設定されていません。")

# Intents 設定
intents = discord.Intents.default()
intents.message_content = True  # jishaku用
intents.members = True          # メンバー情報を扱う

bot = commands.Bot(command_prefix="!", intents=intents)  # !jsk用にprefix残す

# ギルドID（開発時は自分のサーバーIDを入れると同期が速い）
GUILD_ID = int(os.getenv("GUILD_ID", "0"))  # .envにGUILD_ID=サーバーID を入れると便利

@bot.event
async def on_ready():
    print(f"ログインしました: {bot.user} (ID: {bot.user.id})")
    
    # jishaku をロード（!jsk でデバッグ可能）
    try:
        await bot.load_extension("jishaku")
        print("jishaku をロードしました。(!jsk で使用)")
    except Exception as e:
        print(f"jishaku のロードに失敗しました: {e}")
    
    # スラッシュコマンド同期
    try:
        synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID) if GUILD_ID else None)
        print(f"スラッシュコマンドを {len(synced)} 個同期しました。")
    except Exception as e:
        print(f"スラッシュコマンド同期エラー: {e}")

# --- 日本語スラッシュコマンド群（nuggets） ---

@bot.tree.command(name="残高確認", description="残高を確認します")
@app_commands.describe(member="確認するユーザー（未指定時は自分）")
async def 残高確認(interaction: discord.Interaction, member: discord.Member = None):
    """残高確認スラッシュコマンド"""
    target = member or interaction.user
    bal = bank.get_balance(target.id)
    await interaction.response.send_message(f"{target.mention} の残高は **{bal} nuggets** です。")

@bot.tree.command(name="送金", description="他のユーザーにnuggetsを送金します")
@app_commands.describe(member="送金先のユーザー", amount="送金額")
async def 送金(interaction: discord.Interaction, member: discord.Member, amount: int):
    """送金スラッシュコマンド"""
    if amount <= 0:
        await interaction.response.send_message("❌ 0 より大きい金額を指定してください。", ephemeral=True)
        return
    if member.id == interaction.user.id:
        await interaction.response.send_message("❌ 自分自身には送金できません。", ephemeral=True)
        return

    ok = bank.transfer(interaction.user.id, member.id, amount)
    if not ok:
        await interaction.response.send_message("❌ 残高が不足しています。", ephemeral=True)
        return

    await interaction.response.send_message(
        f"✅ {interaction.user.mention} から {member.mention} に **{amount} nuggets** を送金しました！"
    )

@bot.tree.command(name="付与", description="ユーザーにnuggetsを付与します（管理者専用）")
@app_commands.describe(member="付与先のユーザー", amount="付与金額")
async def 付与(interaction: discord.Interaction, member: discord.Member, amount: int):
    """付与スラッシュコマンド"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ このコマンドを実行する権限がありません。", ephemeral=True)
        return
        
    if amount == 0:
        await interaction.response.send_message("❌ 0 以外の金額を指定してください。", ephemeral=True)
        return
    new_bal = bank.add_balance(member.id, amount)
    await interaction.response.send_message(
        f"✅ {member.mention} に **{amount} nuggets** を付与しました！\n現在の残高: **{new_bal} nuggets**"
    )

# --- チンチロ（チンチロリン）コマンド ---
def _score_roll(roll):
    """ロール(3個のダイス)から順位を返す。
    返り値: (rank:int, label:str)
    rank の大きい方が勝ち。特別値:
      -1: 1-2-3(自動負け)
       0: メンツ無し（ペアもトリプルもなし）→負け扱い
      >=1 and <=6: ペアありでシングルの目が点数（1-6）
      >=100: ゾロ目（トリプル） -> 100 + face
    """
    s = sorted(roll)
    # 1-2-3 自動負け
    if s == [1, 2, 3]:
        return -1, "1-2-3（自動負け）"
    # トリプル
    if s[0] == s[1] == s[2]:
        return 100 + s[0], f"ゾロ目 {s[0]}-{s[1]}-{s[2]}"
    # ペア判定
    if s[0] == s[1] or s[1] == s[2]:
        # シングルの目を返す
        if s[0] == s[1]:
            single = s[2]
        else:
            single = s[0]
        return single, f"ペア {roll[0]}-{roll[1]}-{roll[2]}（点：{single}）"
    # メンツ無し
    return 0, f"メンツ無し {roll[0]}-{roll[1]}-{roll[2]}"


import asyncio

@bot.tree.command(name="チンチロ", description="チンチロリンをプレイします（掛け金）")
@app_commands.describe(amount="掛け金（nuggets）")
async def チンチロ(interaction: discord.Interaction, amount: int):
    """インタラクティブなチンチロコマンド（確認ボタン・埋め込み表示・再戦ボタン付き）"""
    if amount <= 0:
        await interaction.response.send_message("❌ 0 より大きい金額を指定してください。", ephemeral=True)
        return
    uid = interaction.user.id
    bal = bank.get_balance(uid)
    if bal < amount:
        await interaction.response.send_message("❌ 残高が不足しています。", ephemeral=True)
        return

    # 確認ビュー
    class ConfirmView(discord.ui.View):
        def __init__(self, author_id: int, amount: int):
            super().__init__(timeout=60)
            self.author_id = author_id
            self.amount = amount
            self._timed_out = False

        async def on_timeout(self):
            """ビューがタイムアウトしたときの処理: ボタン無効化とメッセージ更新"""
            self._timed_out = True
            self.disable_all_items()
            try:
                if hasattr(self, "message") and self.message:
                    await self.message.edit(content="⏳ 時間切れです。確認の期限が切れました。/チンチロ で再度実行してください。", view=self)
            except Exception:
                pass

        def disable_all_items(self):
            """Safely disable all components in this view."""
            for item in list(self.children):
                try:
                    item.disabled = True
                except Exception:
                    pass

        @discord.ui.button(label="実行する", style=discord.ButtonStyle.success)
        async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
            # すぐに ACK（defer）してからフォローアップで即時メッセージを送る（Interaction timeout を回避）
            try:
                await interaction.response.defer(ephemeral=True)
                try:
                    await interaction.followup.send("処理を開始しました。しばらくお待ちください...", ephemeral=True)
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    print(f"[chinchiro] followup send failed (start): {e}")
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"[chinchiro] initial defer failed: {e}")

            # 有効期限切れチェック
            if getattr(self, "_timed_out", False):
                try:
                    await interaction.response.send_message("⏳ この確認は期限切れです。/チンチロ を再実行してください。", ephemeral=True)
                except Exception:
                    try:
                        await interaction.followup.send("⏳ この確認は期限切れです。/チンチロ を再実行してください。", ephemeral=True)
                    except Exception:
                        pass
                return

            # 実行者チェック
            print(f"[chinchiro] confirm pressed by {interaction.user.id} for amount={self.amount} (acked)")
            if interaction.user.id != self.author_id:
                try:
                    await interaction.followup.send("❌ この操作はコマンド実行者しか行えません。", ephemeral=True)
                except Exception:
                    pass
                return

            # 最終残高チェック
            cur = bank.get_balance(self.author_id)
            if cur < self.amount:
                try:
                    await interaction.followup.send("❌ 実行時に残高不足でした。", ephemeral=True)
                except Exception:
                    pass
                self.disable_all_items()
                try:
                    await interaction.message.edit(view=self)
                except Exception:
                    pass
                return

            # 本処理を try/except で囲む
            try:
                    # 払い込み
                    bank.add_balance(self.author_id, -self.amount)

                    # シミュレーション（ロールアニメーション）
                    die_faces = ["⚀","⚁","⚂","⚃","⚄","⚅"]
                    rolling_embed = discord.Embed(title=f"チンチロ: {interaction.user.display_name}", description=f"掛け金: {self.amount} nuggets\n振っています…", color=0x3498db)
                    try:
                        rolling_msg = await interaction.followup.send(embed=rolling_embed)
                    except Exception as e:
                        import traceback
                        traceback.print_exc()
                        print(f"[chinchiro] followup send failed (rolling): {e}")
                        # フォールバック：可能なら元メッセージを編集
                        try:
                            await interaction.message.edit(content="振っています…", view=None)
                            rolling_msg = interaction.message
                        except Exception:
                            rolling_msg = None

                    # 3回短いアニメーション
                    for _ in range(3):
                        tmp_p = [random.randint(1, 6) for _ in range(3)]
                        tmp_d = [random.randint(1, 6) for _ in range(3)]
                        try:
                            if rolling_msg is not None:
                                await rolling_msg.edit(embed=discord.Embed(
                                    title=rolling_embed.title,
                                    description=(f"掛け金: {self.amount} nuggets\n\n"
                                                 f"🎲 あなた: {die_faces[tmp_p[0]-1]} {die_faces[tmp_p[1]-1]} {die_faces[tmp_p[2]-1]}\n"
                                                 f"🤖 ディーラー: {die_faces[tmp_d[0]-1]} {die_faces[tmp_d[1]-1]} {die_faces[tmp_d[2]-1]}\n\n"
                                                 f"振っています…"),
                                    color=0x3498db
                                ))
                            else:
                                # フォールバック: 元の確認メッセージを編集
                                try:
                                    parent = getattr(interaction, "message", None) or await interaction.original_response()
                                    if parent:
                                        await parent.edit(content="振っています…", view=None)
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        await asyncio.sleep(0.6)

                    # 最終ロール
                    player_roll = [random.randint(1, 6) for _ in range(3)]
                    dealer_roll = [random.randint(1, 6) for _ in range(3)]
                    p_rank, p_label = _score_roll(player_roll)
                    d_rank, d_label = _score_roll(dealer_roll)

                    # 判定
                    result_text = ""
                    payout = 0
                    outcome = "lose"
                    if p_rank == d_rank:
                        result_text = "引き分け：掛け金を返却しました。"
                        bank.add_balance(self.author_id, self.amount)
                        outcome = "draw"
                    else:
                        if p_rank == -1:
                            result_text = "あなたは 1-2-3 を出し自動負けです（掛け金没収）。"
                            outcome = "lose"
                        elif d_rank == -1:
                            mult = 3 if p_rank >= 100 else 1
                            payout = self.amount * (1 + mult)
                            bank.add_balance(self.author_id, payout)
                            result_text = f"おめでとう！ディーラーが1-2-3で自動負け。あなたの勝ち（+{payout}）"
                            outcome = "win"
                        else:
                            if p_rank > d_rank:
                                mult = 3 if p_rank >= 100 else 1
                                payout = self.amount * (1 + mult)
                                bank.add_balance(self.author_id, payout)
                                result_text = f"勝ち！ +{payout} を獲得しました。"
                                outcome = "win"
                            else:
                                result_text = "残念、あなたの負けです（掛け金没収）。"
                                outcome = "lose"

                    # 結果埋め込み
                    color = 0x95a5a6
                    if outcome == "win":
                        color = 0x2ecc71
                    elif outcome == "lose":
                        color = 0xe74c3c

                    embed = discord.Embed(title=f"チンチロ - 結果: {interaction.user.display_name}", color=color)
                    embed.add_field(name="あなた", value=(f"{die_faces[player_roll[0]-1]} {die_faces[player_roll[1]-1]} {die_faces[player_roll[2]-1]}\n{p_label}"), inline=True)
                    embed.add_field(name="ディーラー", value=(f"{die_faces[dealer_roll[0]-1]} {die_faces[dealer_roll[1]-1]} {die_faces[dealer_roll[2]-1]}\n{d_label}"), inline=True)
                    embed.add_field(name="結果", value=result_text, inline=False)
                    embed.set_footer(text=f"現在の残高: {bank.get_balance(self.author_id)} nuggets")

                    # 結果ビュー
                    class ResultView(discord.ui.View):
                        def __init__(self, author_id: int, amount: int):
                            super().__init__(timeout=120)
                            self.author_id = author_id
                            self.amount = amount
                            self._timed_out = False

                        async def on_timeout(self):
                            self._timed_out = True
                            for item in list(self.children):
                                try:
                                    item.disabled = True
                                except Exception:
                                    pass
                            try:
                                if hasattr(self, "message") and self.message:
                                    await self.message.edit(content="⏳ 表示の有効期限が切れました。もう一度 /チンチロ を実行してください。", view=self)
                            except Exception:
                                pass

                        @discord.ui.button(label="もう一度", style=discord.ButtonStyle.primary)
                        async def again(self, interaction: discord.Interaction, button: discord.ui.Button):
                            if getattr(self, "_timed_out", False):
                                try:
                                    await interaction.response.send_message("⏳ この結果の有効期限は切れています。/チンチロ を再実行してください。", ephemeral=True)
                                except Exception:
                                    pass
                                return

                            if interaction.user.id != self.author_id:
                                try:
                                    await interaction.response.send_message("❌ この操作はコマンド実行者しか行えません。", ephemeral=True)
                                except Exception:
                                    pass
                                return
                            # 同額で再戦するため、確認ビューを再表示する
                            try:
                                await interaction.response.defer(ephemeral=True)
                                try:
                                    await interaction.followup.send("同額で再戦します。確認してください。", ephemeral=True, view=ConfirmView(self.author_id, self.amount))
                                except Exception as e:
                                    print(f"[chinchiro] again followup failed: {e}")
                            except Exception as e:
                                print(f"[chinchiro] again defer failed: {e}")

                        @discord.ui.button(label="閉じる", style=discord.ButtonStyle.secondary)
                        async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
                            if getattr(self, "_timed_out", False):
                                try:
                                    await interaction.response.send_message("⏳ この結果の有効期限は切れています。メッセージは自動で消えるかもしれません。", ephemeral=True)
                                except Exception:
                                    pass
                                return

                            if interaction.user.id != self.author_id:
                                try:
                                    await interaction.response.send_message("❌ この操作はコマンド実行者しか行えません。", ephemeral=True)
                                except Exception:
                                    pass
                                return
                            try:
                                await interaction.response.defer(ephemeral=True)
                            except Exception:
                                pass
                            try:
                                await interaction.message.delete()
                            except Exception:
                                pass

                    # メッセージ編集（結果表示）
                    self.disable_all_items()
                    try:
                        # interaction.message が None の場合は original_response を取得して編集する
                        msg = getattr(interaction, "message", None)
                        if msg is None:
                            try:
                                msg = await interaction.original_response()
                            except Exception:
                                try:
                                    msg = await interaction.fetch_original_response()
                                except Exception:
                                    msg = None
                        if msg is not None:
                            await msg.edit(view=self)
                    except Exception:
                        pass

                    # 結果用 View を作成してメッセージを送信し、送信メッセージを view.message に保存
                    rv = ResultView(self.author_id, self.amount)
                    try:
                        result_msg = await interaction.followup.send(embed=embed, view=rv, ephemeral=False, wait=True)
                        try:
                            rv.message = result_msg
                        except Exception:
                            pass
                    except Exception as e:
                        import traceback
                        traceback.print_exc()
                        print(f"[chinchiro] followup send failed (result): {e}")
                        try:
                            await interaction.followup.send(embed=embed, ephemeral=False)
                        except Exception:
                            pass

            except Exception as e:
                import traceback
                traceback.print_exc()
                try:
                    await interaction.followup.send(f"エラーが発生しました: {e}", ephemeral=True)
                except Exception:
                    pass

        @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
        async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
            # defer first to ACK
            try:
                await interaction.response.defer(ephemeral=True)
                try:
                    await interaction.followup.send("キャンセル処理を開始しました。", ephemeral=True)
                except Exception as e:
                    print(f"[chinchiro] cancel followup failed: {e}")
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"[chinchiro] cancel initial defer failed: {e}")

            print(f"[chinchiro] cancel pressed by {interaction.user.id} (acked)")
            if interaction.user.id != self.author_id:
                try:
                    await interaction.followup.send("❌ この操作はコマンド実行者しか行えません。", ephemeral=True)
                except Exception:
                    pass
                return
            self.disable_all_items()
            try:
                await interaction.message.edit(content="キャンセルされました。", view=self)
            except Exception:
                pass
            try:
                await interaction.followup.send("キャンセルしました。", ephemeral=True)
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"[chinchiro] cancel followup failed: {e}")

    # 確認メッセージ
    confirm_view = ConfirmView(author_id=uid, amount=amount)
    await interaction.response.send_message(f"掛け金 **{amount} nuggets** でチンチロを実行します。よろしいですか？", ephemeral=True, view=confirm_view)
    # original_response をキャッシュして view.message に保存（編集やタイムアウト時に利用）
    try:
        orig = await interaction.original_response()
        confirm_view.message = orig
    except Exception:
        try:
            # 代替: fetch original response
            orig = await interaction.fetch_original_response()
            confirm_view.message = orig
        except Exception:
            pass

# 管理者向け: スラッシュコマンドを強制同期して一覧を返す（デバッグ用）
@bot.tree.command(name="sync", description="(管理者) スラッシュコマンドを同期して登録一覧を表示")
@app_commands.describe(only_guild="True にすると GUILD_ID または現在のギルドで同期します")
async def sync(interaction: discord.Interaction, only_guild: bool = False):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ このコマンドを実行する権限がありません。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    try:
        guild_obj = None
        if only_guild or GUILD_ID:
            # GUILD_ID が設定されていればそちらを優先
            if GUILD_ID:
                guild_obj = discord.Object(id=GUILD_ID)
            else:
                guild_obj = interaction.guild

        synced = await bot.tree.sync(guild=guild_obj)
        # 登録済みコマンドを取得して名前を列挙
        fetched = await bot.tree.fetch_commands(guild=guild_obj)
        names = ", ".join([c.name for c in fetched]) if fetched else "(なし)"
        await interaction.followup.send(f"同期しました: {len(synced)} 個\n登録済みコマンド: {names}", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"同期エラー: {e}", ephemeral=True)

# ping コマンド（動作確認用）
@bot.tree.command(name="ping", description="Botの応答確認")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 pong!")

bot.run(TOKEN)