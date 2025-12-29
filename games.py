import random
import asyncio
from typing import List, Tuple

import discord
from discord.ext import commands
from discord import app_commands

import bank

# --- ヘルパー関数 ---

CARD_RANKS = ["A"] + [str(i) for i in range(2, 11)] + ["J", "Q", "K"]


def build_deck() -> List[str]:
    # 52枚デッキ（スートは不要なので rank のみ）
    deck = []
    for _ in range(4):
        deck.extend(CARD_RANKS)
    random.shuffle(deck)
    return deck


def card_value(rank: str) -> int:
    if rank == "A":
        return 11
    if rank in ("J", "Q", "K"):
        return 10
    return int(rank)


def hand_value(cards: List[str]) -> Tuple[int, bool]:
    # returns (best_value, is_soft)
    total = 0
    aces = 0
    for c in cards:
        if c == "A":
            aces += 1
            total += 11
        else:
            total += card_value(c)

    # Convert Aces from 11 -> 1 as needed
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1

    is_soft = any(c == "A" for c in cards) and total + 10 <= 21
    return total, is_soft


# --- Cog ---
class Games(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --- スロット ---
    @app_commands.command(name="スロット", description="スロットをプレイします（掛け金）")
    @app_commands.describe(amount="掛け金（nuggets）")
    async def スロット(self, interaction: discord.Interaction, amount: int):
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
                self._timed_out = True
                for item in list(self.children):
                    try:
                        item.disabled = True
                    except Exception:
                        pass
                try:
                    if hasattr(self, "message") and self.message:
                        await self.message.edit(content="⏳ 時間切れです。/スロット で再度実行してください。", view=self)
                except Exception:
                    pass

            @discord.ui.button(label="実行する", style=discord.ButtonStyle.success)
            async def confirm(self, i: discord.Interaction, button: discord.ui.Button):
                await i.response.defer(ephemeral=True)
                if i.user.id != self.author_id:
                    await i.followup.send("❌ この操作はコマンド実行者しか行えません。", ephemeral=True)
                    return
                # 最終残高チェック
                if bank.get_balance(self.author_id) < self.amount:
                    await i.followup.send("❌ 実行時に残高不足でした。", ephemeral=True)
                    self.disable_all_items()
                    try:
                        await i.message.edit(view=self)
                    except Exception:
                        pass
                    return

                # 払い込み
                bank.add_balance(self.author_id, -self.amount)

                # スロットの実行
                symbols = ["🍒", "⭐", "💎", "🍋", "🍊", "🔔"]
                rolling_embed = discord.Embed(title=f"スロット: {i.user.display_name}", description=f"掛け金: {self.amount} nuggets\n振っています…", color=0x3498db)
                try:
                    rolling_msg = await i.followup.send(embed=rolling_embed)
                except Exception:
                    try:
                        await i.message.edit(content="振っています…", view=None)
                        rolling_msg = i.message
                    except Exception:
                        rolling_msg = None

                # アニメーション
                for _ in range(4):
                    tmp = [random.choice(symbols) for _ in range(3)]
                    try:
                        if rolling_msg is not None:
                            await rolling_msg.edit(embed=discord.Embed(
                                title=rolling_embed.title,
                                description=(f"掛け金: {self.amount} nuggets\n\n"
                                             f"{tmp[0]} {tmp[1]} {tmp[2]}\n\n"
                                             f"振っています…"),
                                color=0x3498db
                            ))
                    except Exception:
                        pass
                    await asyncio.sleep(0.6)

                # 最終結果
                final = [random.choice(symbols) for _ in range(3)]
                payout = 0
                outcome = "lose"
                # 3つ一致
                if final[0] == final[1] == final[2]:
                    payout = self.amount * 10  # 10倍配当
                    outcome = "win"
                # 2つ一致
                elif final[0] == final[1] or final[1] == final[2] or final[0] == final[2]:
                    payout = self.amount * 2  # 2倍
                    outcome = "win"
                else:
                    outcome = "lose"

                result_color = 0x95a5a6
                result_text = "残念、あなたの負けです（掛け金没収）。"
                if outcome == "win":
                    bank.add_balance(self.author_id, payout)
                    result_color = 0x2ecc71
                    result_text = f"おめでとう！ +{payout} を獲得しました。"
                embed = discord.Embed(title=f"スロット - 結果: {i.user.display_name}", color=result_color)
                embed.add_field(name="絵柄", value=(f"{final[0]} {final[1]} {final[2]}"), inline=False)
                embed.add_field(name="結果", value=result_text, inline=False)
                embed.set_footer(text=f"現在の残高: {bank.get_balance(self.author_id)} nuggets")

                # 結果を送信
                try:
                    await i.followup.send(embed=embed)
                except Exception:
                    pass

                self.disable_all_items()
                try:
                    await i.message.edit(view=self)
                except Exception:
                    pass

            def disable_all_items(self):
                for item in list(self.children):
                    try:
                        item.disabled = True
                    except Exception:
                        pass

            @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
            async def cancel(self, i: discord.Interaction, button: discord.ui.Button):
                await i.response.defer(ephemeral=True)
                if i.user.id != self.author_id:
                    await i.followup.send("❌ この操作はコマンド実行者しか行えません。", ephemeral=True)
                    return
                self.disable_all_items()
                try:
                    await i.message.edit(content="キャンセルされました。", view=self)
                except Exception:
                    pass
                try:
                    await i.followup.send("キャンセルしました。", ephemeral=True)
                except Exception:
                    pass

        confirm_view = ConfirmView(author_id=uid, amount=amount)
        await interaction.response.send_message(f"掛け金 **{amount} nuggets** でスロットを実行します。よろしいですか？", ephemeral=True, view=confirm_view)
        try:
            orig = await interaction.original_response()
            confirm_view.message = orig
        except Exception:
            try:
                orig = await interaction.fetch_original_response()
                confirm_view.message = orig
            except Exception:
                pass

    # --- ブラックジャック ---
    @app_commands.command(name="ブラックジャック", description="ブラックジャックをプレイします（掛け金）")
    @app_commands.describe(amount="掛け金（nuggets）")
    async def ブラックジャック(self, interaction: discord.Interaction, amount: int):
        if amount <= 0:
            await interaction.response.send_message("❌ 0 より大きい金額を指定してください。", ephemeral=True)
            return
        uid = interaction.user.id
        bal = bank.get_balance(uid)
        if bal < amount:
            await interaction.response.send_message("❌ 残高が不足しています。", ephemeral=True)
            return

        # 払い込み
        bank.add_balance(uid, -amount)

        deck = build_deck()

        # 初期配り
        def draw_card() -> str:
            nonlocal deck
            if not deck:
                deck = build_deck()
            return deck.pop()

        player_cards = [draw_card(), draw_card()]
        dealer_cards = [draw_card(), draw_card()]

        # View と状態管理
        class BJView(discord.ui.View):
            def __init__(self, author_id: int, bet: int):
                super().__init__(timeout=180)
                self.author_id = author_id
                self.bet = bet
                self.stood = False
                self.can_double = True  # 最初のアクションのみダブル可
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
                        await self.message.edit(content="⏳ 表示の有効期限が切れました。/ブラックジャック を再実行してください。", view=self)
                except Exception:
                    pass

            def _embed(self, reveal_dealer: bool = False) -> discord.Embed:
                # Dealer の隠しカードを表示するかどうか
                p_val, _ = hand_value(player_cards)
                if reveal_dealer:
                    d_val, _ = hand_value(dealer_cards)
                    dealer_text = (" ".join(dealer_cards) + f"\n合計: {d_val}")
                else:
                    dealer_text = (dealer_cards[0] + " ❓")
                embed = discord.Embed(title=f"ブラックジャック: {interaction.user.display_name}")
                embed.add_field(name="あなた", value=(" ".join(player_cards) + f"\n合計: {p_val}"), inline=False)
                embed.add_field(name="ディーラー", value=dealer_text, inline=False)
                embed.set_footer(text=f"掛け金: {self.bet} nuggets  | 現在の残高: {bank.get_balance(self.author_id)} nuggets")
                return embed

            async def finish_game(self, result: str, payout: int, reveal_dealer: bool = True):
                # result: "win"/"lose"/"draw"
                # payout: amount to add back (includes stake if applicable)
                color = 0x95a5a6
                if result == "win":
                    color = 0x2ecc71
                elif result == "lose":
                    color = 0xe74c3c
                embed = self._embed(reveal_dealer=reveal_dealer)
                embed.color = color
                if result == "win":
                    embed.add_field(name="結果", value=f"あなたの勝ち！ +{payout} を獲得しました。", inline=False)
                    bank.add_balance(self.author_id, payout)
                elif result == "lose":
                    embed.add_field(name="結果", value=f"あなたの負けです（掛け金没収）。", inline=False)
                else:
                    embed.add_field(name="結果", value=f"引き分け：掛け金を返却しました。", inline=False)
                    bank.add_balance(self.author_id, payout)

                # disable buttons
                for item in list(self.children):
                    try:
                        item.disabled = True
                    except Exception:
                        pass
                try:
                    await self.message.edit(embed=embed, view=self)
                except Exception:
                    pass

            async def dealer_play_and_resolve(self, double_bet: int = 0):
                # ディーラーはソフト17でヒット
                while True:
                    val, is_soft = hand_value(dealer_cards)
                    # Soft 17 でヒット
                    if val < 17 or (val == 17 and is_soft):
                        dealer_cards.append(draw_card())
                        continue
                    break

                p_val, _ = hand_value(player_cards)
                d_val, _ = hand_value(dealer_cards)

                if p_val > 21:
                    # プレイヤーバースト
                    await self.finish_game("lose", 0, reveal_dealer=True)
                    return
                if d_val > 21:
                    # ディーラーバースト
                    payout = (self.bet + double_bet) * 2
                    await self.finish_game("win", payout, reveal_dealer=True)
                    return

                if p_val > d_val:
                    payout = (self.bet + double_bet) * 2
                    await self.finish_game("win", payout, reveal_dealer=True)
                elif p_val < d_val:
                    await self.finish_game("lose", 0, reveal_dealer=True)
                else:
                    # 引き分け
                    await self.finish_game("draw", (self.bet + double_bet), reveal_dealer=True)

            @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary)
            async def hit(self, i: discord.Interaction, button: discord.ui.Button):
                await i.response.defer()
                if i.user.id != self.author_id:
                    await i.followup.send("❌ この操作はコマンド実行者しか行えません。", ephemeral=True)
                    return
                # ドロー
                player_cards.append(draw_card())
                self.can_double = False
                if hasattr(self, "message") and self.message:
                    try:
                        await self.message.edit(embed=self._embed(reveal_dealer=False), view=self)
                    except Exception:
                        pass
                p_val, _ = hand_value(player_cards)
                if p_val > 21:
                    # バースト
                    await self.finish_game("lose", 0, reveal_dealer=True)

            @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary)
            async def stand(self, i: discord.Interaction, button: discord.ui.Button):
                await i.response.defer()
                if i.user.id != self.author_id:
                    await i.followup.send("❌ この操作はコマンド実行者しか行えません。", ephemeral=True)
                    return
                self.can_double = False
                await self.dealer_play_and_resolve(double_bet=0)

            @discord.ui.button(label="Double", style=discord.ButtonStyle.success)
            async def double(self, i: discord.Interaction, button: discord.ui.Button):
                await i.response.defer()
                if i.user.id != self.author_id:
                    await i.followup.send("❌ この操作はコマンド実行者しか行えません。", ephemeral=True)
                    return
                if not self.can_double:
                    await i.followup.send("❌ ダブルダウンは最初のアクションでのみ可能です。", ephemeral=True)
                    return
                # 追加の賭け金を払う（残高チェック）
                extra = self.bet
                if bank.get_balance(self.author_id) < extra:
                    await i.followup.send("❌ ダブルダウンに必要な残高がありません。", ephemeral=True)
                    return
                bank.add_balance(self.author_id, -extra)
                # プレイヤーはカードを1枚引いて自動的にスタンド
                player_cards.append(draw_card())
                # 表示更新
                try:
                    if hasattr(self, "message") and self.message:
                        await self.message.edit(embed=self._embed(reveal_dealer=False), view=self)
                except Exception:
                    pass
                # ディーラー処理（bet doubled）
                await self.dealer_play_and_resolve(double_bet=extra)

        view = BJView(author_id=uid, bet=amount)
        await interaction.response.send_message(embed=view._embed(reveal_dealer=False), view=view)
        try:
            orig = await interaction.original_response()
            view.message = orig
        except Exception:
            try:
                view.message = await interaction.fetch_original_response()
            except Exception:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Games(bot))
